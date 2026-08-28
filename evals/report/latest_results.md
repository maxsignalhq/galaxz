# Eval Execution Report

- Started: `2026-08-28T22:52:40.022472+00:00`
- Completed: `2026-08-28T22:52:40.141350+00:00`
- Duration: `0.119s`
- Scenarios: `4`
- Passed suites: `9`
- Failed suites: `0`

## Suites

### contracts_registry
- Status: `passed`
- Check: TaskContract creation and validation
- Check: Pulsar registration for Vega and Rigel
- Check: Skill lookup for QA and engineering paths

### vega_pipeline
- Status: `passed`
- Check: Finance Vega flow
- Check: Health Vega flow
- Check: Hospitality Vega flow
- Check: Retail Vega flow
- Artifacts: `{"finance_ach_payroll": {"bugs": 1, "feedback_stream": "galaxz.feedback.vega", "run_id": "d9a9024e-a59b-47e1-a99b-f5a272a8b5e9"}, "health_fhir_intake": {"bugs": 1, "feedback_stream": "galaxz.feedback.vega", "run_id": "b55ad56a-8777-4261-8372-19a9dbad3406"}, "hospitality_booking": {"bugs": 1, "feedback_stream": "galaxz.feedback.vega", "run_id": "a9769581-f71d-4033-a98d-0001b21d5b77"}, "retail_gtin_catalog": {"bugs": 0, "feedback_stream": "galaxz.feedback.vega", "run_id": "5482b79f-da95-418b-88a0-39ab7735e1ef"}}`

### rigel_skills
- Status: `passed`
- Check: Code generation with execution calibration
- Check: Test writing
- Check: PR review
- Check: Debug triage
- Check: Refactor
- Check: Scaffold
- Artifacts: `{"codegen_confidence": 0.988, "feedback_events": 6}`

### andromeda_routing
- Status: `passed`
- Check: Vega routing
- Check: Rigel routing
- Check: No-match routing
- Check: Task log persistence
- Artifacts: `{"rigel_task_id": "13660af7-9561-4806-9eb2-408d954a9c23", "vega_task_id": "5c1aea91-e45a-4a11-892c-d18d25f8c370"}`

### goal_execution
- Status: `passed`
- Check: Goal DAG completion
- Check: Goal rollup completed count
- Check: Goal rollup total count
- Artifacts: `{"goal_id": "f238e723-d148-40bb-bf38-7b55a1d0e69a", "status": "complete"}`

### cli_surface
- Status: `passed`
- Check: CLI Vega command
- Check: CLI route command

### api_surface
- Status: `passed`
- Check: FastAPI health endpoint
- Check: FastAPI bearer auth for write endpoints
- Check: FastAPI task routing endpoint
- Check: FastAPI status endpoint
- Check: FastAPI review queue approve/reject endpoints
- Check: FastAPI fine-tune candidate approve/reject endpoints

### orion_pipeline
- Status: `passed`
- Check: Direct Orion ingest for accepted and rejected feedback
- Check: Dataset curation cycle
- Check: Heuristic cycle with routing, drift, and fine-tune signals
- Artifacts: `{"heuristic_streams": ["aether:orion.drift_alert", "aether:orion.fine_tune_ready", "aether:routing.heuristic_update"], "ingest_dataset_root": "/var/folders/gy/0hlyycgx1k17_04kb4836njr0000gn/T/galaxz-eval-orion-5bp1wz72/datasets"}`

### feedback_handshake
- Status: `passed`
- Check: Andromeda to Vega execution
- Check: Andromeda to Rigel execution
- Check: Agent feedback payload compatibility with Orion ingest
- Artifacts: `{"eligible_ingests": 2, "feedback_events": 2}`

## Dataset Sources

- finance: Nacha ACH (https://achdevguide.nacha.org/ach-file-overview)
- health: HL7 FHIR Patient and Observation (https://www.hl7.org/fhir/patient.html)
- hospitality: OpenTravel Messaging (https://opentravel.org/opentravel-messaging-business-functionality/)
- retail: GS1 GTIN / Barcode Standards (https://www.gs1.org/standards/barcodes)
