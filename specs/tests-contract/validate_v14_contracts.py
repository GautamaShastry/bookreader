from pathlib import Path
import json,yaml,re
from jsonschema import Draft202012Validator, FormatChecker
root=Path(__file__).resolve().parents[1]
api=yaml.safe_load((root/'06-API-OPENAPI.yaml').read_text())
assert api['info']['version']=='1.4.0'
assert '/v1/books/{book_id}/full-summary' in api['paths']
assert set(api['paths']['/v1/books/{book_id}/full-summary'])=={'post','get'}
assert 'full_book_summary' in api['components']['schemas']['Job']['properties']['job_type']['enum']
assert any(p.get('name')=='Idempotency-Key' and p.get('required') for p in api['paths']['/v1/books/{book_id}/full-summary']['post']['parameters'])
for p in root.glob('schemas/*.json'):
    schema=json.loads(p.read_text()); Draft202012Validator.check_schema(schema)
S=json.loads((root/'schemas/book-full-summary.schema.json').read_text())
example=json.loads((root/'examples/book-full-summary-example.json').read_text())
Draft202012Validator(S,format_checker=FormatChecker()).validate(example)
for case in [
 {**example,'book_id':'invalid'},
 {**example,'overview_claims':[{'claim_id':'c','text':'false','source_ids':[]}]},
 {**example,'status':'unapproved'}]:
    assert list(Draft202012Validator(S,format_checker=FormatChecker()).iter_errors(case)),'Negative schema case unexpectedly passed'
for route,path in api['paths'].items():
  for method,op in path.items():
    if method not in ('get','post','put','patch','delete'):continue
    assert op.get('operationId')
    for r in re.findall(r"#/components/schemas/([A-Za-z_][A-Za-z0-9_]*)",json.dumps(op)):
       assert r in api['components']['schemas'], (route,method,r)
text='\n'.join((root/f).read_text() for f in ['10-DECISION-RECORD.md','15-DECISION-FREEZE-AND-DEVELOPMENT-CONTRACT.md'])
for adr in ('ADR-014','ADR-015','ADR-016'):
 assert adr in text
assert 'no paid aws deployment without approval' in (root/'AGENTS.md').read_text().lower()
print('v1.4 contract checks PASS: JSON Schema, example, negative cases, OpenAPI refs, freeze markers')
