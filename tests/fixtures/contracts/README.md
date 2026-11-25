# Contract test fixtures

`malformed-schemas/` holds deliberately broken JSON Schemas. They must **fail** the contract
validator (`python -m bookscope_contracts tests/fixtures/contracts/malformed-schemas`) with a
diagnostic naming the file and the location of the problem. `tests/unit/contracts/test_malformed_schema.py`
asserts that failure; do not "fix" these files.
