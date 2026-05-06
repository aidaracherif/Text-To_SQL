# Tests — Text-to-SQL DGD Sénégal

Suite de tests unitaires avec mocks pour assurer la robustesse du backend.
**Aucune dépendance externe requise** : pas besoin de PostgreSQL, Ollama ou Qdrant.

## 🚀 Lancer les tests

```bash
# Installer les dépendances de test
pip install pytest pytest-asyncio pytest-mock pytest-cov httpx

# Tous les tests (rapide, ~6 secondes)
pytest

# Avec verbose
pytest -v

# Un seul fichier
pytest tests/test_pipeline.py

# Avec rapport de couverture
pytest --cov=core --cov=api --cov-report=term-missing
```

## 📊 Couverture actuelle

| Fichier | Tests | Cible |
|---|---|---|
| `tests/test_sql_extractor.py` | 36 | Extraction, validation, fix SQL |
| `tests/test_pipeline.py` | 16 | Orchestration, erreurs, auto-repair |
| `tests/test_prompt_builder.py` | 15 | Construction des prompts |
| `tests/test_smart_retriever.py` | 30 | Routage RAG (lexical + scores) |
| `tests/test_audit_repository.py` | 10 | Robustesse de l'audit (jamais crasher) |
| `tests/test_api_routes.py` | 21 | Endpoints `/query`, `/health`, `/history` |
| **TOTAL** | **128** | |

**Couverture** : 71% sur le code métier (`core/`, `features/`, `api/`).

## 🎯 Philosophie

- **Tests unitaires avec mocks** — aucune dépendance externe
- **< 7 secondes** pour la suite complète
- **Déterministes** — pas de flakiness
- **Documentent le comportement attendu** plutôt que le code lui-même

## ➕ Ajouter un test

1. Choisir le bon fichier (`test_<module>.py`) ou en créer un nouveau
2. Utiliser les fixtures de `conftest.py` (`fake_llm`, `fake_db`, etc.)
3. Lancer `pytest -v` pour vérifier

Exemple :

```python
def test_my_feature(fake_llm, fake_db, fake_schema_loader):
    fake_llm.chat.return_value = "```sql\nSELECT 1;\n```"
    # ... ton test
```
