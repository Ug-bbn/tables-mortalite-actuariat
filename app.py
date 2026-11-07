"""Application Flask : table de mortalité et pyramide des âges (données Insee)."""
import base64
import binascii
from pathlib import Path

import plotly.graph_objects as go
from flask import Flask, abort, render_template, request
from plotly.offline import get_plotlyjs_version

import actuariat as act

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024  # les tableaux Insee font quelques dizaines de Ko

DATA = Path(__file__).parent / "data"
TABLE_DEFAUT = DATA / "insee_table_mortalite_2020_2022.xls"
PYRAMIDE_DEFAUT = DATA / "insee_pyramide_ages_2025.xlsx"
PLOTLY_JS = f"https://cdn.plot.ly/plotly-{get_plotlyjs_version()}.min.js"  # même version que plotly installé
COULEURS = {"Hommes": "#3b82c4", "Femmes": "#c2417a", "Les deux sexes": "#4b5563"}


def fichier_source(defaut: Path) -> tuple[bytes, str | None]:
    """Fichier importé, ou ré-envoyé par un champ caché lors d'un nouveau calcul, sinon le fichier Insee fourni.
    Rien n'est jamais écrit sur le disque : le nom choisi par l'utilisateur ne sert qu'à l'affichage."""
    fichier = request.files.get("fichier")
    if fichier and fichier.filename:
        if not fichier.filename.lower().endswith((".xls", ".xlsx")):
            abort(400, "Format non pris en charge : envoyez un fichier .xls ou .xlsx.")
        return fichier.read(), fichier.filename
    if request.form.get("contenu"):
        try:
            return base64.b64decode(request.form["contenu"], validate=True), request.form.get("nom") or "fichier importé"
        except binascii.Error:
            abort(400, "Fichier ré-envoyé illisible : importez-le à nouveau.")
    return defaut.read_bytes(), None


def nombre(nom: str, defaut, mini, maxi, type_=int):
    try:
        valeur = type_(str(request.values.get(nom, defaut)).replace(",", "."))  # « 2,5 » accepté
    except ValueError:
        abort(400, f"« {nom} » doit être un nombre.")
    if not mini <= valeur <= maxi:
        abort(400, f"« {nom} » doit être compris entre {mini} et {maxi}.")
    return valeur


def graphique(fig: go.Figure, titre_x: str, titre_y: str) -> str:
    fig.update_layout(xaxis_title=titre_x, yaxis_title=titre_y, plot_bgcolor="white", height=420,
                      margin=dict(l=40, r=20, t=30, b=40), legend=dict(orientation="h", y=1.08))
    return fig.to_html(full_html=False, include_plotlyjs=False)


@app.context_processor
def variables_communes():
    return {"plotly_js": PLOTLY_JS}


@app.errorhandler(400)
def erreur_requete(e):
    return render_template("erreur.html", message=e.description), 400


@app.errorhandler(413)
def fichier_trop_gros(e):
    return render_template("erreur.html", message="Fichier trop volumineux (2 Mo maximum)."), 413


@app.errorhandler(act.FormatInvalide)
def format_invalide(e):
    return render_template("erreur.html", message=str(e)), 400


@app.route("/")
def accueil():
    return render_template("index.html")


@app.route("/mortalite", methods=["GET", "POST"])
def mortalite():
    contenu, nom = fichier_source(TABLE_DEFAUT)
    table = act.lire_table_mortalite(contenu)

    sexe = request.values.get("sexe", "Les deux sexes")
    if sexe not in act.SEXES:
        abort(400, "Sexe inconnu.")
    age_depart = nombre("age_depart", 0, 0, act.AGE_MAX)
    age_arrivee = nombre("age_arrivee", 65, age_depart, act.AGE_MAX)
    age_rente = nombre("age_rente", 65, 0, act.AGE_MAX)
    taux_pct = nombre("taux", "2", 0.0, 10.0, float)
    montant = nombre("montant", 12_000, 0, 1_000_000)

    t = table[table["sexe"] == sexe]
    survie = go.Figure([go.Scatter(x=g["age"], y=g["survivants"], name=s, line_color=COULEURS[s])
                        for s, g in table.groupby("sexe", sort=False)])
    esperance = go.Figure([go.Scatter(x=g["age"], y=g["esperance"], name=s, line_color=COULEURS[s])
                           for s, g in table.groupby("sexe", sort=False)])

    lignes = t.set_index("age").assign(
        quotient=act.quotients_mortalite(t),
        recalculee=act.esperance_recalculee(t),
    ).reset_index()
    lignes["ecart"] = lignes["recalculee"] - lignes["esperance"]
    rente = act.rente_viagere(t, age_rente, taux_pct / 100)

    return render_template(
        "mortalite.html", nom=nom, contenu_b64=base64.b64encode(contenu).decode() if nom else "",
        sexes=act.SEXES, sexe=sexe, lignes=lignes.to_dict("records"),
        survie_html=graphique(survie, "Âge", "Survivants sur 100 000 naissances"),
        esperance_html=graphique(esperance, "Âge", "Espérance de vie (années)"),
        age_depart=age_depart, age_arrivee=age_arrivee,
        proba=act.probabilite_survie(t, age_depart, age_arrivee),
        age_rente=age_rente, taux_pct=taux_pct, montant=montant,
        rente=rente, capital=rente * montant,
        ecart_max=lignes["ecart"].abs().max(),
    )


@app.route("/demographie", methods=["GET", "POST"])
def demographie():
    contenu, nom = fichier_source(PYRAMIDE_DEFAUT)
    p = act.lire_pyramide(contenu)

    pyramide = go.Figure([
        go.Bar(y=p["age"], x=-p["hommes"], name="Hommes", orientation="h", marker_color=COULEURS["Hommes"],
               customdata=p["hommes"], hovertemplate="%{y} ans : %{customdata} milliers"),
        go.Bar(y=p["age"], x=p["femmes"], name="Femmes", orientation="h", marker_color=COULEURS["Femmes"],
               hovertemplate="%{y} ans : %{x} milliers"),
    ])
    maxi = int(p[["hommes", "femmes"]].max().max() // 100 + 1) * 100
    graduations = list(range(-maxi, maxi + 1, 100))
    pyramide.update_layout(barmode="relative", bargap=0.05, height=620,
                           xaxis=dict(tickvals=graduations, ticktext=[str(abs(v)) for v in graduations]))

    tranches = act.synthese_tranches(p)
    barres = go.Figure(go.Bar(x=tranches["tranche"], y=tranches["effectif"] / 1000,
                              marker_color=["#7fc97f", "#f0b429", "#e8743b"],
                              text=[f"{v * 100:.1f} %".replace(".", ",") for v in tranches["part"]], textposition="outside"))

    return render_template(
        "demographie.html", nom=nom,
        tranches=tranches.to_dict("records"), total=tranches["effectif"].sum(),
        pyramide_html=graphique(pyramide, "Effectif (milliers)", "Âge"),
        barres_html=graphique(barres, "", "Effectif (millions)"),
    )


if __name__ == "__main__":
    app.run()  # debug désactivé : la console de débogage Flask permet d'exécuter du code à distance
