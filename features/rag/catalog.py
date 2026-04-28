"""
features/rag/catalog.py — Catalogues de données pour le RAG.
Regroupe les exemples SQL, les connaissances métier et le schéma.
"""

# =============================================================================
# EXEMPLES SQL (paires question / SQL pour few-shot learning)
# =============================================================================

SQL_EXAMPLES = [
    {
        "question": "Combien de déclarations y a-t-il au total ?",
        "sql": "SELECT COUNT(*) AS total_declarations FROM declarations;"
    },
    {
        "question": "Liste de tous les bureaux de douane disponibles",
        "sql": "SELECT id_bureau, nom_bureau, ville, code_bureau FROM bureaux ORDER BY nom_bureau;"
    },
    {
        "question": "Quels sont les régimes douaniers existants ?",
        "sql": "SELECT code_regime, libelle FROM regimes ORDER BY code_regime;"
    },
    {
        "question": "Liste des opérateurs suspendus",
        "sql": (
            "SELECT id_operateur, raison_sociale, ninea, type_operateur "
            "FROM operateurs WHERE statut = 'SUSPENDU' ORDER BY raison_sociale LIMIT 1000;"
        )
    },
    {
        "question": "Déclarations enregistrées en 2023",
        "sql": (
            "SELECT id_declaration, numero_declaration, date_enregistrement, statut "
            "FROM declarations "
            "WHERE EXTRACT(YEAR FROM date_enregistrement) = 2023 "
            "ORDER BY date_enregistrement DESC LIMIT 1000;"
        )
    },
    {
        "question": "Déclarations en contentieux",
        "sql": (
            "SELECT d.id_declaration, d.numero_declaration, d.date_enregistrement, "
            "       o.raison_sociale, b.nom_bureau "
            "FROM declarations d "
            "JOIN operateurs o ON d.id_operateur = o.id_operateur "
            "JOIN bureaux b ON d.id_bureau = b.id_bureau "
            "WHERE d.statut = 'CONTENTIEUX' "
            "ORDER BY d.date_enregistrement DESC LIMIT 1000;"
        )
    },
    {
        "question": "Nombre de déclarations par bureau",
        "sql": (
            "SELECT b.nom_bureau, b.ville, COUNT(*) AS nb_declarations "
            "FROM declarations d "
            "JOIN bureaux b ON d.id_bureau = b.id_bureau "
            "GROUP BY b.nom_bureau, b.ville ORDER BY nb_declarations DESC;"
        )
    },
    {
        "question": "Top 10 des opérateurs par valeur déclarée",
        "sql": (
            "SELECT o.raison_sociale, o.type_operateur, "
            "       SUM(d.valeur_totale) AS valeur_totale, COUNT(*) AS nb_declarations "
            "FROM declarations d "
            "JOIN operateurs o ON d.id_operateur = o.id_operateur "
            "GROUP BY o.raison_sociale, o.type_operateur "
            "ORDER BY valeur_totale DESC LIMIT 10;"
        )
    },
    {
        "question": "Total des taxes perçues par type de droit",
        "sql": (
            "SELECT type_droit, libelle_droit, SUM(montant) AS montant_total "
            "FROM droits_taxes WHERE statut_paiement = 'PAYE' "
            "GROUP BY type_droit, libelle_droit ORDER BY montant_total DESC;"
        )
    },
    {
        "question": "Répartition des déclarations par statut",
        "sql": (
            "SELECT statut, COUNT(*) AS nb_declarations FROM declarations "
            "GROUP BY statut ORDER BY nb_declarations DESC;"
        )
    },
    {
        "question": "Nombre de déclarations par année",
        "sql": (
            "SELECT EXTRACT(YEAR FROM date_enregistrement) AS annee, COUNT(*) AS nb_declarations "
            "FROM declarations GROUP BY annee ORDER BY annee DESC;"
        )
    },
    {
        "question": "Montant total de TVA collectée en 2023",
        "sql": (
            "SELECT SUM(dt.montant) AS tva_totale_2023 "
            "FROM droits_taxes dt "
            "JOIN declarations d ON dt.id_declaration = d.id_declaration "
            "WHERE dt.type_droit = 'TVA' AND dt.statut_paiement = 'PAYE' "
            "AND EXTRACT(YEAR FROM d.date_enregistrement) = 2023;"
        )
    },
    {
        "question": "Top 5 des catégories de marchandises les plus importées par valeur",
        "sql": (
            "SELECT m.code_categorie, SUM(m.valeur_totale) AS valeur_totale, COUNT(*) AS nb_lignes "
            "FROM marchandises m "
            "JOIN declarations d ON m.id_declaration = d.id_declaration "
            "WHERE d.code_regime = 'IM' "
            "GROUP BY m.code_categorie ORDER BY valeur_totale DESC LIMIT 5;"
        )
    },
]


# =============================================================================
# CONNAISSANCES MÉTIER DOUANIÈRES
# =============================================================================

KNOWLEDGE = [
    {
        "titre": "Régime IM — Importation définitive",
        "type": "regime", "code": "IM",
        "contenu": (
            "Le régime IM correspond à la mise à la consommation (importation définitive). "
            "Les marchandises entrent sur le territoire sénégalais de manière permanente. "
            "Ce régime génère obligatoirement DD, TVA, RS, et éventuellement PCS et PE. "
            "C'est le régime le plus fréquent dans la base."
        )
    },
    {
        "titre": "Régime TF — Transit",
        "type": "regime", "code": "TF",
        "contenu": (
            "Le régime TF correspond au transit douanier. Les marchandises traversent le territoire "
            "sénégalais sans être mises à la consommation, destinées à un pays tiers (Mali, Burkina). "
            "Aucun droit de douane n'est perçu, mais une garantie de transit est exigée."
        )
    },
    {
        "titre": "Régime AT — Admission temporaire",
        "type": "regime", "code": "AT",
        "contenu": (
            "Le régime AT correspond à l'admission temporaire. Les marchandises entrent sans paiement "
            "immédiat des droits, sous condition de ressortir dans un délai fixé (6-12 mois). "
            "Une caution bancaire est exigée. Utilisé pour équipements et machines."
        )
    },
    {
        "titre": "DD — Droit de douane",
        "type": "taxe", "code": "DD",
        "contenu": (
            "Le DD (Droit de douane) est la taxe principale perçue à l'importation, calculée sur la "
            "valeur CIF. Le taux varie selon la catégorie : 0% nécessités, 5% matières premières, "
            "10% biens intermédiaires, 20% biens de consommation."
        )
    },
    {
        "titre": "TVA à l'importation",
        "type": "taxe", "code": "TVA",
        "contenu": (
            "La TVA à l'importation est calculée sur la valeur CIF plus le droit de douane. "
            "Le taux standard au Sénégal est de 18%. "
            "Elle s'applique à la quasi-totalité des importations sauf exonérations spéciales."
        )
    },
    {
        "titre": "Cycle de vie d'une déclaration",
        "type": "procedure",
        "contenu": (
            "Une déclaration douanière passe par : ENREGISTREE → EN_COURS → VALIDEE → LIQUIDEE. "
            "Elle peut aussi être ABANDONNEE (opérateur y renonce) ou en CONTENTIEUX "
            "(litige entre opérateur et douane sur la valeur ou classification)."
        )
    },
    {
        "titre": "Types d'opérateurs économiques",
        "type": "operateur",
        "contenu": (
            "Types d'opérateurs : IMPORTATEUR (achète à l'étranger), EXPORTATEUR (vend à l'étranger), "
            "MIXTE (les deux), TRANSITAIRE (intermédiaire logistique). "
            "Statuts : ACTIF, SUSPENDU (temporaire), RADIÉ (définitif). "
            "Le NINEA est l'identifiant fiscal unique sénégalais obligatoire."
        )
    },
    {
        "titre": "Codes de catégories de marchandises",
        "type": "marchandise",
        "contenu": (
            "Catégories : AGRO=agricole, ALIM=alimentaire, AUTO=véhicules, BOIS=bois, CHIM=chimique, "
            "CONST=construction, COSM=cosmétiques, ELEC=électronique, HYDRO=hydrocarbures, "
            "MACH=machines, METAL=métaux, PECHE=pêche, PHARM=médicaments, TABAC=tabac, TEXT=textiles."
        )
    },
    {
        "titre": "Calcul des taxes douanières",
        "type": "calcul",
        "contenu": (
            "Dans droits_taxes, montant = base_imposition × taux. "
            "La base_imposition est généralement la valeur CIF (valeur_totale dans declarations). "
            "Pour la TVA, la base inclut aussi le DD. "
            "Le taux est sous forme décimale (ex: 0.18 pour 18%)."
        )
    },
]


# =============================================================================
# DESCRIPTIONS DE TABLES (pour le retrieval sémantique)
# =============================================================================

SCHEMA = [
    {
        "table": "pays",
        "description": (
            "Table de référence des pays. Colonnes : code_pays (CHAR 2, clé primaire, code ISO), "
            "libelle (nom du pays). Jointure type : JOIN pays p ON d.pays_origine = p.code_pays"
        ),
    },
    {
        "table": "regimes",
        "description": (
            "Table de référence des régimes douaniers. code_regime (CHAR 2), libelle. "
            "Régimes : IM=importation, EX=exportation, AT=admission temporaire, TF=transit, ZF=zone franche. "
            "Jointure : JOIN regimes r ON d.code_regime = r.code_regime"
        ),
    },
    {
        "table": "bureaux",
        "description": (
            "Table des bureaux de douane du Sénégal. id_bureau, nom_bureau, ville, code_bureau. "
            "Bureaux principaux : Dakar Port, Dakar Aéroport, Kaolack, Ziguinchor, Saint-Louis, Kidira. "
            "Jointure : JOIN bureaux b ON d.id_bureau = b.id_bureau"
        ),
    },
    {
        "table": "operateurs",
        "description": (
            "Table des opérateurs économiques agréés. id_operateur, raison_sociale, ninea, "
            "type_operateur (EXPORTATEUR/IMPORTATEUR/MIXTE/TRANSITAIRE), statut (ACTIF/RADIÉ/SUSPENDU). "
            "Jointure : JOIN operateurs o ON d.id_operateur = o.id_operateur"
        ),
    },
    {
        "table": "declarations",
        "description": (
            "Table centrale des déclarations en douane. id_declaration, numero_declaration, "
            "date_enregistrement, id_operateur, id_bureau, code_regime, pays_origine, "
            "valeur_totale (FCFA), statut (ABANDONNEE/CONTENTIEUX/EN_COURS/ENREGISTREE/LIQUIDEE/VALIDEE). "
            "Alias standard : d. Environ 1000 déclarations couvrant 2021-2024."
        ),
    },
    {
        "table": "marchandises",
        "description": (
            "Table des lignes de marchandises par déclaration. id_marchandise, id_declaration, "
            "code_categorie, designation, quantite, unite, valeur_totale, poids_kg. "
            "Jointure : JOIN marchandises m ON m.id_declaration = d.id_declaration"
        ),
    },
    {
        "table": "droits_taxes",
        "description": (
            "Table des droits et taxes par déclaration. id_droit, id_declaration, "
            "type_droit (DD/PCS/PE/RS/TVA), libelle_droit, taux, base_imposition, montant, "
            "statut_paiement (CONTENTIEUX/EN_ATTENTE/EXONERE/PAYE). "
            "Jointure : JOIN droits_taxes dt ON dt.id_declaration = d.id_declaration"
        ),
    },
]
