# Eval Execution Report

- Started: `2026-05-09T16:34:23.801168+00:00`
- Completed: `2026-05-09T16:34:24.151002+00:00`
- Duration: `0.35s`
- Scenarios: `4`
- Passed suites: `8`
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
- Artifacts: `{"finance_ach_payroll": {"bugs": 1, "feedback_stream": "galaxz.feedback.vega", "run_id": "98f9e80c-de32-44a4-b051-8906ed139f19"}, "health_fhir_intake": {"bugs": 1, "feedback_stream": "galaxz.feedback.vega", "run_id": "c02a9084-f23f-4c37-90b7-67a98a66db77"}, "hospitality_booking": {"bugs": 1, "feedback_stream": "galaxz.feedback.vega", "run_id": "0dfbdf1b-0503-4c7a-91c2-dcc0e16dac58"}, "retail_gtin_catalog": {"bugs": 0, "feedback_stream": "galaxz.feedback.vega", "run_id": "ca8ffd0a-0619-43c7-9f9d-6caf98f6279d"}}`

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
- Artifacts: `{"rigel_task_id": "406ddc59-18b7-4307-9e2b-079f8706176a", "vega_task_id": "b66e0941-fd00-45c5-be46-7c74ea3bac8a"}`

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
- Artifacts: `{"heuristic_streams": ["aether:orion.drift_alert", "aether:orion.fine_tune_ready", "aether:routing.heuristic_update"], "ingest_dataset_root": "/var/folders/gy/0hlyycgx1k17_04kb4836njr0000gn/T/galaxz-eval-orion-_21hz_ij/datasets"}`

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
