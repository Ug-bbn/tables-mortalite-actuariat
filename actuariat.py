"""Lecture des tableaux Insee et calculs actuariels sur une table de mortalité.

Hypothèse de calcul : entre deux âges publiés (table abrégée : 0, 1, 5, 10…), les survivants
décroissent linéairement. Au-delà du dernier âge publié, ils décroissent géométriquement
à un rythme calé sur l'espérance de vie publiée à cet âge.
"""
import io

import numpy as np
import pandas as pd

SEXES = ["Hommes", "Femmes", "Les deux sexes"]
AGE_MAX = 120


class FormatInvalide(ValueError):
    """Le fichier ne correspond pas au format Insee attendu (message lisible par l'utilisateur)."""


def _lire_excel(contenu: bytes) -> pd.DataFrame:
    try:
        return pd.read_excel(io.BytesIO(contenu), header=None, engine="calamine")
    except Exception as e:  # fichier corrompu, mot de passe, autre format…
        raise FormatInvalide("Le fichier n'est pas un classeur Excel lisible.") from e


def _ligne_entete(brut: pd.DataFrame) -> int:
    lignes = brut.index[brut[0].astype(str).str.strip() == "Âge x"]
    if lignes.empty:
        raise FormatInvalide("Colonne « Âge x » introuvable : ce n'est pas un tableau Insee par âge.")
    return lignes[0]


def _lignes_par_age(brut: pd.DataFrame, entete: int) -> pd.DataFrame:
    donnees = brut.iloc[entete + 1:].copy()
    donnees[0] = pd.to_numeric(donnees[0], errors="coerce")
    return donnees[donnees[0].notna()]  # on s'arrête aux notes de bas de tableau


# ---------- Table de mortalité ----------

def lire_table_mortalite(contenu: bytes) -> pd.DataFrame:
    """Table Insee (en-têtes sur deux lignes : sexe, puis S(x)/E(x)) -> colonnes age, sexe, survivants, esperance."""
    brut = _lire_excel(contenu)
    entete = _ligne_entete(brut)
    sexes = brut.iloc[entete - 1].ffill()  # cellules fusionnées « Hommes | Hommes »
    donnees = _lignes_par_age(brut, entete)

    morceaux = []
    for sexe in SEXES:
        cols = {str(brut.iat[entete, c]).strip(): c for c in brut.columns if sexes[c] == sexe}
        if not {"S(x)", "E(x)"} <= cols.keys():
            raise FormatInvalide(f"Colonnes S(x) et E(x) introuvables pour « {sexe} ».")
        morceaux.append(pd.DataFrame({
            "age": donnees[0].astype(int).to_numpy(),
            "sexe": sexe,
            "survivants": pd.to_numeric(donnees[cols["S(x)"]], errors="coerce").to_numpy(),
            "esperance": pd.to_numeric(donnees[cols["E(x)"]], errors="coerce").to_numpy(),
        }))
    table = pd.concat(morceaux, ignore_index=True)
    _valider_table(table)
    return table


def _valider_table(table: pd.DataFrame) -> None:
    if table[["survivants", "esperance"]].isna().any().any():
        raise FormatInvalide("Valeurs manquantes ou non numériques dans la table.")
    for sexe, t in table.groupby("sexe"):
        if t["age"].iloc[0] != 0 or not t["age"].is_monotonic_increasing or t["age"].duplicated().any():
            raise FormatInvalide(f"Les âges doivent commencer à 0 et être croissants ({sexe}).")
        if (t["survivants"] <= 0).any() or not t["survivants"].is_monotonic_decreasing:
            raise FormatInvalide(f"Le nombre de survivants doit être positif et décroissant ({sexe}).")


def table_annuelle(t: pd.DataFrame) -> pd.Series:
    """Survivants S(x) pour chaque âge entier de 0 à AGE_MAX, pour un sexe."""
    ages, survivants = t["age"].to_numpy(), t["survivants"].to_numpy(float)
    annuelle = pd.Series(np.interp(np.arange(ages[-1] + 1), ages, survivants))
    # queue géométrique S(x+k) = S(x)·q^k, avec q tel que l'aire restante vaut S(x)·E(x)
    e = t["esperance"].iloc[-1]
    q = (2 * e - 1) / (2 * e + 1)
    queue = survivants[-1] * q ** np.arange(1, AGE_MAX - ages[-1] + 1)
    return pd.concat([annuelle, pd.Series(queue, index=range(ages[-1] + 1, AGE_MAX + 1))])


def esperance_recalculee(t: pd.DataFrame) -> pd.Series:
    """Espérance de vie aux âges publiés, recalculée à partir des seuls survivants (méthode des trapèzes)."""
    ages, s = t["age"].to_numpy(), t["survivants"].to_numpy(float)
    annees_vecues = np.diff(ages) * (s[:-1] + s[1:]) / 2
    restant = np.append(np.cumsum(annees_vecues[::-1])[::-1], 0) + s[-1] * t["esperance"].iloc[-1]
    return pd.Series(restant / s, index=ages)


def quotients_mortalite(t: pd.DataFrame) -> pd.Series:
    """Probabilité de décéder entre un âge publié et le suivant."""
    s = t["survivants"].to_numpy(float)
    return pd.Series(np.append(1 - s[1:] / s[:-1], np.nan), index=t["age"].to_numpy())


def probabilite_survie(t: pd.DataFrame, age_depart: int, age_arrivee: int) -> float:
    if not 0 <= age_depart <= age_arrivee <= AGE_MAX:
        raise ValueError("âges invalides")
    s = table_annuelle(t)
    return s[age_arrivee] / s[age_depart]


def rente_viagere(t: pd.DataFrame, age: int, taux: float) -> float:
    """Valeur actuelle d'une rente de 1 €/an versée en début d'année tant que la personne est en vie."""
    if not 0 <= age <= AGE_MAX or not 0 <= taux < 1:
        raise ValueError("âge ou taux invalide")
    s = table_annuelle(t).loc[age:]
    actualisation = (1.0 + taux) ** -np.arange(len(s), dtype=float)
    return float((s.to_numpy() / s.iloc[0] * actualisation).sum())


# ---------- Pyramide des âges ----------

TRANCHES = {"Moins de 20 ans": (0, 19), "20 à 64 ans": (20, 64), "65 ans ou plus": (65, AGE_MAX)}


def lire_pyramide(contenu: bytes) -> pd.DataFrame:
    """Pyramide Insee (colonnes Âge x, Mixte, Femmes, Hommes, en milliers) -> age, ensemble, femmes, hommes."""
    brut = _lire_excel(contenu)
    entete = _ligne_entete(brut)
    cols = {str(v).strip(): c for c, v in brut.iloc[entete].items()}
    if not {"Mixte", "Femmes", "Hommes"} <= cols.keys():
        raise FormatInvalide("Colonnes « Mixte », « Femmes » et « Hommes » introuvables.")
    donnees = _lignes_par_age(brut, entete)
    p = pd.DataFrame({
        "age": donnees[0].astype(int).to_numpy(),
        **{nom: pd.to_numeric(donnees[cols[col]], errors="coerce").to_numpy()
           for nom, col in [("ensemble", "Mixte"), ("femmes", "Femmes"), ("hommes", "Hommes")]},
    })
    if p.isna().any().any() or (p[["ensemble", "femmes", "hommes"]] < 0).any().any():
        raise FormatInvalide("Effectifs manquants, non numériques ou négatifs.")
    if (p["ensemble"] - p["femmes"] - p["hommes"]).abs().max() > 1:  # arrondis au millier
        raise FormatInvalide("Incohérence : « Mixte » diffère de Femmes + Hommes.")
    return p


def synthese_tranches(p: pd.DataFrame) -> pd.DataFrame:
    lignes = [{"tranche": nom, "effectif": p.loc[p["age"].between(a, b), "ensemble"].sum()}
              for nom, (a, b) in TRANCHES.items()]
    s = pd.DataFrame(lignes)
    s["part"] = s["effectif"] / s["effectif"].sum()
    return s
