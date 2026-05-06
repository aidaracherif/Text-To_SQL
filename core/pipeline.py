"""
core/pipeline.py — Orchestrateur pur du pipeline Text-to-SQL.
Ne contient que la logique métier. Les I/O sont dans infrastructure/.
"""

import time
from core.models import QueryResult
from core.prompt_builder import build_system_prompt, build_rag_prompt
from core.sql_extractor import extract_sql, validate_sql, is_out_of_schema, fix_sql


def run_pipeline(
    question: str,
    schema_loader,
    llm_client,
    db_connector,
    rag_retriever=None,
    verbose: bool = False,
) -> QueryResult:
    """
    Exécute le pipeline complet Text-to-SQL.
    """
    result = QueryResult(question=question)
    t0 = time.time()

    try:
        # ── 1. Charger le schéma ─────────────────────────────
        schema_text, stats_text = schema_loader.get_schema_and_stats()

        # ── 2. Construire le prompt ──────────────────────────
        if rag_retriever is not None:
            
            context = rag_retriever.retrieve(question)
            user_prompt = build_rag_prompt(question, context)
            system_prompt = build_system_prompt(schema_text, stats_text)
            # Audit : conserver le contexte RAG et la route choisie
            result.rag_context = context
            result.rag_route = context.get("_route")
        else:
            system_prompt = build_system_prompt(schema_text, stats_text)
            user_prompt = question

        # Audit : conserver les prompts
        result.system_prompt = system_prompt
        result.user_prompt = user_prompt

        if verbose:
            print(f"\n[QUESTION] {question}")
            print("[INFO] Génération SQL en cours...")

        # ── 3. Appel LLM ─────────────────────────────────────
        llm_response = llm_client.chat(system_prompt, user_prompt)
        result.llm_raw_output = llm_response  # Audit : réponse brute du LLM

        # ── 4. Extraction SQL ────────────────────────────────
        sql = fix_sql(extract_sql(llm_response))
        result.sql = sql

        if verbose:
            print(f"\n[SQL]\n{sql}")

        # ── 5. Hors périmètre ? ──────────────────────────────
        if is_out_of_schema(sql):
            result.warning = "Question hors périmètre du schéma douanier."
            return result

        # ── 6. Validation sécurité SQL ────────────────────────
        validate_sql(sql)

        # ── 7. Exécution avec auto-repair ────────────────────
        try:
            columns, rows = db_connector.execute(sql)

        except Exception as exec_err:
            if verbose:
                print(f"[REPAIR] Erreur : {exec_err}")

            repair_prompt = (
                f"Cette requête SQL a échoué :\n{sql}\n\n"
                f"Erreur PostgreSQL : {exec_err}\n\n"
                f"Corrige uniquement l'erreur et retourne le SQL corrigé."
            )

            llm_response2 = llm_client.chat(system_prompt, repair_prompt)
            sql = fix_sql(extract_sql(llm_response2))
            result.sql = sql

            if verbose:
                print(f"[REPAIR] SQL corrigé :\n{sql}")

            validate_sql(sql)

            # 2ème tentative après correction
            columns, rows = db_connector.execute(sql)

        # ── 8. Stockage résultats ────────────────────────────
        result.columns = columns
        result.rows = rows
        result.row_count = len(rows)

    except Exception as exc:
        result.error = str(exc)
        if verbose:
            print(f"[ERREUR] {exc}")

    finally:
        result.duration_ms = (time.time() - t0) * 1000

    return result