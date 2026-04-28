# 📘 Guide complet — Migration Streamlit → FastAPI + Angular

## Pourquoi FastAPI est le bon choix ?

Votre architecture actuelle est déjà excellente (clean architecture, séparation core/features/infrastructure).
Le seul composant à remplacer est la couche UI Streamlit par une **API REST**. FastAPI est idéal car :

- **Natif Python** → zéro réécriture de votre logique métier (core/, features/, infrastructure/)
- **Automatique** → doc interactive générée à `/docs` sans rien écrire
- **Pydantic intégré** → validation des données entrantes/sortantes
- **CORS natif** → Angular peut l'appeler directement
- **Async** → gestion efficace des requêtes simultanées
- **Testé facilement** → avec httpx (pas besoin de Selenium/Playwright)

---

## Structure du projet FastAPI

```
STATISTIQUE_FASTAPI/
│
├── main.py                          # Point d'entrée (à lancer avec uvicorn)
│
├── api/
│   ├── dependencies.py              # Injection de dépendances (≈ session_state Streamlit)
│   ├── schemas.py                   # Modèles Pydantic (validation requêtes/réponses)
│   └── routers/
│       ├── query.py                 # POST /api/v1/query  ← endpoint principal
│       ├── health.py                # GET  /api/v1/health
│       └── history.py              # GET  /api/v1/history
│
├── core/                            # ✅ INCHANGÉ — votre logique métier
│   ├── models.py
│   ├── pipeline.py
│   ├── prompt_builder.py
│   └── sql_extractor.py
│
├── features/text_to_sql/            # ✅ INCHANGÉ
│   └── service.py
│
├── infrastructure/                  # ✅ INCHANGÉ
│   ├── database/
│   ├── llm/
│   └── vectorstore/
│
├── config/                          # ✅ INCHANGÉ
│   └── settings.py
│
├── requirements.txt
└── .env.example
```

**Ce qui a changé** : uniquement le dossier `ui/` (supprimé) et `app/streamlit_app.py` (remplacé par `main.py`).

---

## Installation

### 1. Créer un environnement virtuel

```bash
cd STATISTIQUE_FASTAPI
python -m venv .venv

# Activer (Linux/Mac)
source .venv/bin/activate

# Activer (Windows)
.venv\Scripts\activate
```

### 2. Installer les dépendances

```bash
pip install -r requirements.txt
```

### 3. Configurer le .env

```bash
cp .env.example .env
# Éditez .env avec vos vraies valeurs (DB, Ollama, etc.)
```

### 4. Lancer le serveur

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

- `--reload` : redémarrage automatique à chaque modification de code (dev uniquement)
- `--host 0.0.0.0` : accessible depuis le réseau local
- `--port 8000` : port par défaut

---

## Tester l'API

### Documentation interactive (Swagger)
Ouvrez **http://localhost:8000/docs** dans votre navigateur.
Vous pouvez tester tous les endpoints directement depuis cette interface.

### Commandes curl

```bash
# Health check
curl http://localhost:8000/api/v1/health

# Générer une requête SQL
curl -X POST http://localhost:8000/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"question": "Quels sont les 10 opérateurs ayant le plus importé en 2024 ?"}'

# Historique
curl http://localhost:8000/api/v1/history
```

### Réponse type d'un succès

```json
{
  "ok": true,
  "sql": "SELECT operateur, SUM(droits_taxes) as total FROM declarations WHERE ...",
  "columns": ["operateur", "total"],
  "rows": [["ENTREPRISE A", 5000000], ["ENTREPRISE B", 3200000]],
  "narrative": "Classement des opérateurs — 10 résultat(s).",
  "row_count": 10
}
```

### Réponse type d'une erreur

```json
{
  "ok": false,
  "sql": "",
  "error": "Ollama inaccessible. Lancez : ollama serve"
}
```

---

## Intégration Angular

### Service Angular type

```typescript
// src/app/services/query.service.ts

import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

export interface QueryResponse {
  ok: boolean;
  sql?: string;
  columns?: string[];
  rows?: any[][];
  narrative?: string;
  row_count?: number;
  error?: string;
}

@Injectable({ providedIn: 'root' })
export class QueryService {
  private apiUrl = 'http://localhost:8000/api/v1';

  constructor(private http: HttpClient) {}

  // Envoyer une question
  ask(question: string): Observable<QueryResponse> {
    return this.http.post<QueryResponse>(`${this.apiUrl}/query`, { question });
  }

  // Vérifier l'état du serveur
  health(): Observable<any> {
    return this.http.get(`${this.apiUrl}/health`);
  }

  // Récupérer l'historique
  history(): Observable<any> {
    return this.http.get(`${this.apiUrl}/history`);
  }
}
```

### Composant Angular type

```typescript
// src/app/components/chat/chat.component.ts

import { Component } from '@angular/core';
import { QueryService, QueryResponse } from '../../services/query.service';

@Component({
  selector: 'app-chat',
  template: `
    <input [(ngModel)]="question" placeholder="Posez votre question..." />
    <button (click)="ask()" [disabled]="loading">Envoyer</button>
    
    <div *ngIf="loading">Génération SQL en cours...</div>
    
    <div *ngIf="result?.ok">
      <p>{{ result.narrative }}</p>
      <pre>{{ result.sql }}</pre>
      <!-- Afficher result.rows dans un tableau -->
    </div>
    
    <div *ngIf="result && !result.ok" class="error">
      {{ result.error }}
    </div>
  `
})
export class ChatComponent {
  question = '';
  result: QueryResponse | null = null;
  loading = false;

  constructor(private queryService: QueryService) {}

  ask() {
    if (!this.question.trim()) return;
    this.loading = true;
    this.queryService.ask(this.question).subscribe({
      next: (res) => { this.result = res; this.loading = false; },
      error: (err) => { console.error(err); this.loading = false; }
    });
  }
}
```

---

## Comprendre FastAPI (pour débutant)

### Concept 1 : Le Router (≈ page Streamlit)

En Streamlit vous avez des pages (`ui/pages/chat.py`, `ui/pages/stats.py`).
En FastAPI, vous avez des **routers** qui définissent des **endpoints** (URLs).

```python
# Streamlit
if page == "Chat":
    show_chat()

# FastAPI — équivalent
@router.post("/query")        # ← décorateur qui dit "cette fonction répond à POST /query"
async def run_query(body: QueryRequest):
    return {"sql": "SELECT ..."}
```

### Concept 2 : Pydantic (validation automatique)

```python
class QueryRequest(BaseModel):
    question: str   # FastAPI validera AUTOMATIQUEMENT que c'est une string

# Si Angular envoie {"question": 123} → FastAPI retourne automatiquement une erreur 422
# Si Angular envoie {"question": "Quel est..."} → tout va bien
```

### Concept 3 : Depends (injection de dépendances)

C'est l'équivalent de `st.session_state` de Streamlit.

```python
# Streamlit
service = st.session_state["service"]

# FastAPI
async def run_query(service: TextToSQLService = Depends(get_service)):
    # FastAPI injecte automatiquement le service → vous ne le créez pas manuellement
    result = service.ask(question)
```

### Concept 4 : async/await

FastAPI peut gérer plusieurs requêtes simultanément grâce à `async`.
Vos fonctions existantes (service.ask, db.execute) sont synchrones → elles fonctionnent
telles quelles dans FastAPI (il les exécute dans un thread pool automatiquement).

---

## Production (déploiement)

### Lancer sans --reload (production)

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
```

### Avec Gunicorn (plus robuste)

```bash
pip install gunicorn
gunicorn main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
```

### CORS en production

Dans `main.py`, remplacez `"*"` par le domaine réel de votre Angular :

```python
allow_origins=["https://votre-domaine.sn"]
```

---

## Résumé des correspondances Streamlit → FastAPI

| Streamlit                        | FastAPI                              |
|----------------------------------|--------------------------------------|
| `st.session_state["service"]`    | `@lru_cache` dans `dependencies.py`  |
| `st.button("Envoyer")`           | `POST /api/v1/query` (depuis Angular)|
| `st.dataframe(df)`               | `rows` + `columns` dans le JSON      |
| `st.error("message")`            | `{"ok": false, "error": "message"}`  |
| Page "Audit"                     | `GET /api/v1/history`                |
| `run_query()` de pipeline_runner | `run_query()` dans routers/query.py  |
| `st.secrets` / `.env`            | `python-dotenv` + `.env` (identique) |
