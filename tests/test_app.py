import base64
import io
from pathlib import Path

import pytest

from app import TABLE_DEFAUT, PYRAMIDE_DEFAUT, app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    return app.test_client()


def envoi(chemin: Path, nom: str):
    return {"fichier": (io.BytesIO(chemin.read_bytes()), nom)}


@pytest.mark.parametrize("url", ["/", "/mortalite", "/demographie"])
def test_pages(client, url):
    assert client.get(url).status_code == 200


def test_calculs_affiches(client):
    page = client.get("/mortalite?sexe=Les+deux+sexes&age_depart=0&age_arrivee=65").get_data(as_text=True)
    assert "88,7 %" in page


def test_import_table(client):
    r = client.post("/mortalite", data=envoi(TABLE_DEFAUT, "ma_table.XLS"), content_type="multipart/form-data")
    assert r.status_code == 200 and "ma_table.XLS" in r.get_data(as_text=True)


def test_nouveau_calcul_garde_le_fichier_importe(client):
    contenu = base64.b64encode(TABLE_DEFAUT.read_bytes()).decode()
    r = client.post("/mortalite", data={"contenu": contenu, "nom": "ma_table.xls", "age_rente": "70"})
    assert r.status_code == 200 and "ma_table.xls" in r.get_data(as_text=True)


def test_import_ne_cree_aucun_fichier(client, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client.post("/demographie", data=envoi(PYRAMIDE_DEFAUT, "../../app.xlsx"), content_type="multipart/form-data")
    assert list(tmp_path.rglob("*")) == []


def test_nom_de_fichier_echappe(client):
    r = client.post("/demographie", data=envoi(PYRAMIDE_DEFAUT, "<script>alert(1)</script>.xlsx"),
                    content_type="multipart/form-data")
    assert "<script>alert(1)</script>" not in r.get_data(as_text=True)


@pytest.mark.parametrize("donnees", [
    {"fichier": (io.BytesIO(b"x"), "virus.exe")},          # mauvaise extension
    {"fichier": (io.BytesIO(b"pas excel"), "faux.xlsx")},  # contenu illisible
    {"contenu": "%%%pas du base64%%%"},                     # champ caché trafiqué
])
def test_imports_refuses(client, donnees):
    assert client.post("/mortalite", data=donnees, content_type="multipart/form-data").status_code == 400


def test_mauvais_type_de_tableau(client):
    r = client.post("/mortalite", data=envoi(PYRAMIDE_DEFAUT, "pyramide.xlsx"), content_type="multipart/form-data")
    assert r.status_code == 400 and "S(x)" in r.get_data(as_text=True)


@pytest.mark.parametrize("requete", ["age_rente=abc", "age_rente=500", "taux=nan", "sexe=Autre",
                                     "age_depart=70&age_arrivee=60"])
def test_parametres_invalides(client, requete):
    assert client.get(f"/mortalite?{requete}").status_code == 400


def test_taux_avec_virgule(client):
    assert client.get("/mortalite?taux=2,5").status_code == 200


def test_fichier_trop_gros(client):
    gros = {"fichier": (io.BytesIO(b"0" * (3 * 1024 * 1024)), "gros.xlsx")}
    assert client.post("/mortalite", data=gros, content_type="multipart/form-data").status_code == 413
