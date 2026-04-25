# AgentOS — Roadmap MVP v0.3 (6 semaines) + backlog priorisé

Ce document est la roadmap d’exécution de la spec canonique `agentos_mvp_v0_3.md`.

## Règle de consolidation

- `agentos_mvp_v0_3.md` = **source de vérité produit/technique**.
- Ce fichier = **plan de delivery** (priorités, séquence, livrables, risques).
- Le contenu v0.2 est obsolète et ne doit plus être utilisé pour guider l’implémentation.

---


## 0) Suivi d'avancement (mis à jour le 2026-04-25)

### État global
- **Semaine active:** Semaine 1 (Wrap + traces).
- **Progression estimée MVP:** ~25% (wrapper + persistance + instrumentation initiale).
- **Bloquant actuel:** aucun bloquant technique majeur; prochaines étapes = candidates/backtest + config `agentos.yaml`.

### Journal d'avancement
- ✅ Initialisation d'une CLI Python `agentos` (commande `wrap`).
- ✅ Persistance locale SQLite (`runs`, `events`, `decisions`, `outcomes`) + traces JSONL par run.
- ✅ Inspection opérable de base (`runs list`, `runs show`, `runs trace`).
- ✅ Redaction minimale des variables d'environnement sensibles (`TOKEN/SECRET/PASSWORD/KEY`) dans les événements.
- ✅ Commandes d'instrumentation `decision record|list|show` et `outcome record` implémentées.
- ✅ Suite de tests automatisés ajoutée (CLI + stockage) pour maintenir un coverage élevé sur les modules MVP.
- ⏳ À faire immédiatement: détection de candidats (`compile candidates`) et backtest (`compile backtest`) avec métriques.

## 1) Backlog priorisé (non redondant avec la spec)

## P0 — Must-have MVP (wrapper-first + preuves)

1. **Wrapper exécutable sans réécriture**
   - `agentos wrap --intent X -- <command...>` pour script shell, job CI, commande Codex/Claude.
   - Capture run minimale (run_id, commande, timestamps, exit code, stdout/stderr configurables).

2. **Stockage local minimal**
   - SQLite: `runs/events/decisions/outcomes/artifacts/compilation_candidates/compiled_rules`.
   - JSONL: `.agentos/runs/<run_id>/trace.jsonl`.

3. **Instrumentation minimale**
   - `agentos decision record` (incluant `AGENTOS_RUN_ID`).
   - `agentos outcome record`.

4. **Inspection opérable**
   - `runs list/show/trace` et `decisions list/show`.

5. **Sécurité MVP (honnêteté + redaction)**
   - Pas de claim sandboxing.
   - Redaction env secrets + options de désactivation capture stdout/stderr.

6. **Vertical slice complet**
   - `wrap -> decision -> candidates -> backtest -> promote -> rule-first + fallback`.

## P1 — Compilation utile en production contrôlée

1. **Détection candidates v0**
   - Groupement simple par intent/step/output + seuils.

2. **Backtest v0**
   - Métriques standardisées (accuracy, coverage, false positives, abstentions).

3. **Promotion explicite**
   - `compile promote/reject`.
   - Registry local versionné avec métriques et fallback policy.

4. **Rule-first conservateur**
   - Match règle puis fallback par défaut.
   - Skip fallback uniquement sur opt-in explicite.

## P2 — Durcissement et DX (sans dérive plateforme)

1. API Python minimale (optionnelle).
2. Migrations DB + validations config robustes.
3. Packaging/release + tests e2e renforcés.
4. Exports de traces/rapports (sans UI web ni orchestrateur).

---

## 2) Roadmap 6 semaines

## Semaine 1 — Wrap + traces
**But:** brancher AgentOS autour d’un process existant sans le modifier.

**Livrables:**
- `wrap` stable (shell/CI/Codex command).
- run/events persistés.
- trace JSONL écrite par run.

**Definition of Done:**
- Un script existant s’exécute inchangé via `agentos wrap`.

## Semaine 2 — Config + sécurité + inspection
**But:** rendre le wrapper exploitable en CI de manière sûre.

**Livrables:**
- config `agentos.yaml` (intent/source/inputs/artifacts/redaction).
- redaction env + exclusions artefacts.
- `runs list/show/trace`.

**Definition of Done:**
- Données consultables localement, sans fuite évidente de secrets.

## Semaine 3 — Decisions + outcomes
**But:** instrumenter la logique décisionnelle sans coupler les scripts à un framework lourd.

**Livrables:**
- `decision record` + `outcome record`.
- fingerprints + candidate flag.
- exemple GitLab CI local démontrable.

**Definition of Done:**
- Historique de décisions interrogeable et relié aux outcomes.

## Semaine 4 — Candidate detection + backtest
**But:** prouver la boucle de compilation à partir d’historique réel.

**Livrables:**
- `compile candidates/show`.
- `compile backtest` + métriques persistées.

**Definition of Done:**
- Au moins un candidat détecté et backtesté sur des runs répétés.

## Semaine 5 — Promotion + runtime rule-first
**But:** utiliser une règle promue tout en préservant le fallback.

**Livrables:**
- `compile promote/reject`.
- registry local de règles.
- `wrap --rule-first` conservateur.

**Definition of Done:**
- Une règle promue est appliquée quand match, et le process fallback reste actif par défaut.

## Semaine 6 — Stabilisation + release MVP
**But:** verrouiller qualité, limites explicites et non-dérive.

**Livrables:**
- vertical slice documenté end-to-end.
- checklist anti-drift de release.
- documentation finale alignée sur `agentos_mvp_v0_3.md`.

**Definition of Done:**
- MVP démontrable en local/CI, sans orchestrateur ni UI ni claim sandboxing.

---

## 3) Garde-fous d’exécution

- Ne pas implémenter Level 3/4 avant validation Level 1/2.
- Ne pas supprimer le fallback par défaut.
- Ne pas introduire Temporal/LangGraph/UI web sur ce cycle.
- Ne pas transformer AgentOS en assistant conversationnel.

---

## 4) Jalons de validation

1. **M1 (fin S2):** wrapper + traces + sécurité MVP.
2. **M2 (fin S4):** compilation candidate + backtest fonctionnels.
3. **M3 (fin S6):** promotion + rule-first conservateur + vertical slice validé.
