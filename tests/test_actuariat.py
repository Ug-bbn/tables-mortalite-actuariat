from pathlib import Path

import pytest

import actuariat as act

DATA = Path(__file__).parent.parent / "data"
TABLE = act.lire_table_mortalite((DATA / "insee_table_mortalite_2020_2022.xls").read_bytes())
PYRAMIDE = act.lire_pyramide((DATA / "insee_pyramide_ages_2025.xlsx").read_bytes())


def sexe(s):
    return TABLE[TABLE["sexe"] == s]


def test_lecture_table():
    assert set(TABLE["sexe"]) == set(act.SEXES)
    assert (TABLE.groupby("sexe")["survivants"].first() == 100_000).all()
    # valeurs lues dans le fichier Insee
    assert sexe("Hommes").set_index("age").loc[65, "esperance"] == pytest.approx(19.02, abs=0.01)
    assert sexe("Femmes").set_index("age").loc[0, "esperance"] == pytest.approx(85.14, abs=0.01)


def test_probabilite_survie_note_de_lecture_insee():
    # « 88 716 des 100 000 personnes nées en 2020-2022 ont atteint 65 ans »
    assert act.probabilite_survie(sexe("Les deux sexes"), 0, 65) == pytest.approx(0.88716, abs=1e-5)


@pytest.mark.parametrize("s", act.SEXES)
def test_esperance_recalculee_proche_de_l_insee(s):
    t = sexe(s)
    ecart = (act.esperance_recalculee(t) - t.set_index("age")["esperance"]).abs()
    assert ecart.loc[:80].max() < 0.1  # intervalles de 5 ans à mortalité modérée
    assert ecart.max() < 0.3           # 85-99 ans : intervalles longs et mortalité forte


@pytest.mark.parametrize("s", act.SEXES)
def test_rente_a_taux_nul_vaut_esperance_plus_une_demi_annee(s):
    # versée en début d'année : environ une demi-année de plus que l'espérance de vie
    t = sexe(s)
    e65 = t.set_index("age").loc[65, "esperance"]
    assert act.rente_viagere(t, 65, 0) == pytest.approx(e65 + 0.5, abs=0.3)


def test_rente_decroit_avec_le_taux_et_l_age():
    t = sexe("Femmes")
    assert act.rente_viagere(t, 65, 0) > act.rente_viagere(t, 65, 0.02) > act.rente_viagere(t, 65, 0.05)
    assert act.rente_viagere(t, 60, 0.02) > act.rente_viagere(t, 70, 0.02)
    assert act.rente_viagere(sexe("Femmes"), 65, 0.02) > act.rente_viagere(sexe("Hommes"), 65, 0.02)


def test_table_annuelle_decroissante_jusqu_a_120_ans():
    s = act.table_annuelle(sexe("Hommes"))
    assert list(s.index) == list(range(0, act.AGE_MAX + 1))
    assert s.is_monotonic_decreasing and s.iloc[-1] < 1


def test_quotients_mortalite():
    q = act.quotients_mortalite(sexe("Les deux sexes"))
    assert q[0] == pytest.approx(1 - 99_615 / 100_000)
    assert q.dropna().between(0, 1).all()


@pytest.mark.parametrize("args", [(70, 65), (-1, 65), (0, 121)])
def test_ages_invalides(args):
    with pytest.raises(ValueError):
        act.probabilite_survie(sexe("Hommes"), *args)


def test_pyramide():
    assert PYRAMIDE["ensemble"].sum() == 68_611  # 68,6 millions d'habitants (milliers)
    tranches = act.synthese_tranches(PYRAMIDE)
    assert tranches["effectif"].sum() == PYRAMIDE["ensemble"].sum()  # aucun âge oublié
    assert tranches["part"].sum() == pytest.approx(1)


def test_fichier_non_excel_refuse():
    with pytest.raises(act.FormatInvalide):
        act.lire_table_mortalite(b"pas un classeur")


def test_pyramide_n_est_pas_une_table_de_mortalite():
    with pytest.raises(act.FormatInvalide):
        act.lire_table_mortalite((DATA / "insee_pyramide_ages_2025.xlsx").read_bytes())
