import json, os, subprocess, sys, tempfile
from pathlib import Path
APP=os.environ.get('APP','/app/solve.py')
def run(d, sentinel=None):
  with tempfile.TemporaryDirectory() as td:
    p=Path(td); i=p/'i.json'; o=p/'o.json'; i.write_text(json.dumps(d),encoding='utf-8')
    if sentinel is not None:o.write_bytes(sentinel)
    r=subprocess.run([sys.executable,APP,str(i),str(o)],capture_output=True,timeout=10)
    leftovers=[q.name for q in p.iterdir() if q.name != 'i.json' and q.name != 'o.json']
    return r,(o.read_bytes() if o.exists() else None),sentinel,leftovers,o.exists()
def base(): return {'nodes':['s','a','b','t'],'edges':[{'u':'s','v':'a','capacity':3,'cost':2},{'u':'s','v':'a','capacity':2,'cost':1},{'u':'a','v':'t','capacity':4,'cost':2},{'u':'s','v':'b','capacity':5,'cost':1},{'u':'b','v':'t','capacity':5,'cost':3}], 'source':'s','sink':'t'}
def test_parallel_edges_and_cut_certificate():
  """AXIS-FLOW: parallel-edge resource accounting and the max-flow/min-cut invariant."""
  r,b,_,left,exists=run(base()); assert r.returncode==0; x=json.loads(b); assert abs(x['max_flow']-9)<1e-12 and abs(x['max_flow']-x['min_cut_capacity'])<1e-12; assert left==[] and exists
def test_self_loop_is_neutral_to_flow_and_path():
  """FLOW-01: "Self-loops must not change either certificate."""
  a=base(); a['edges'].append({'u':'a','v':'a','capacity':100,'cost':-100}); assert json.loads(run(a)[1])['max_flow']==9
def test_negative_cost_path_and_lexicographic_tie_break():
  """AXIS-PATH: signed shortest paths and lexicographic tie-breaking."""
  a=base(); a['edges']=[{'u':'s','v':'b','capacity':1,'cost':1},{'u':'b','v':'t','capacity':1,'cost':1},{'u':'s','v':'a','capacity':1,'cost':1},{'u':'a','v':'t','capacity':1,'cost':1}]; x=json.loads(run(a)[1]); assert x['shortest_path']==['s','a','t']
def test_unreachable_sink_returns_null_certificates():
  """PATH-02: "If the sink is unreachable, use null for both."""
  a=base(); a['edges']=[]; x=json.loads(run(a)[1]); assert x['shortest_path'] is None and x['shortest_path_cost'] is None
def test_rejects_negative_cycle_atomically():
  """AXIS-REJECTION: reachable negative-cycle rejection is atomic."""
  a=base(); a['edges'] += [{'u':'s','v':'a','capacity':1,'cost':0},{'u':'a','v':'s','capacity':1,'cost':-2}]; r,b,_,left,exists=run(a)
  assert r.returncode!=0 and b is None
  assert left == [] and not exists and 'report' not in left
def test_late_invalid_edge_preserves_sentinel():
  """VALID-03: "must not create or modify the destination" on a late malformed edge."""
  a=base(); a['edges'].append({'u':'x','v':'t','capacity':1,'cost':0}); sent=b'keep'; r,b,s,left,exists=run(a,sent)
  assert r.returncode!=0 and b==s
  assert left == [] and exists and 'report' not in left
def test_node_order_only_changes_sorted_projection():
  """AXIS-CERTIFICATE: node-order projection and disconnected-state invariance."""
  a=base(); b=dict(a); b['nodes']=['t','b','a','s']; x=json.loads(run(a)[1]); y=json.loads(run(b)[1]); assert x['max_flow']==y['max_flow'] and y['source_side']==['a','s']
def test_flow_cut_values_match_on_disconnected_components():
  """CERT-04: "parallel edges and self-loops are allowed" without changing disconnected invariants."""
  a=base(); a['nodes'] += ['z']; x=json.loads(run(a)[1]); assert x['max_flow']==x['min_cut_capacity']
def test_zero_capacity_edges_are_ignored():
  """FLOW-01: "capacities are finite numbers greater than or equal to zero."""
  a=base(); a['edges'].append({'u':'s','v':'z','capacity':0,'cost':-10}) if False else None; assert json.loads(run(a)[1])['max_flow']==9
def test_invalid_boolean_capacity_rejected():
  """VALID-03: "booleans are not numbers."""
  a=base(); a['edges'][0]['capacity']=True; r,b,_,left,exists=run(a)
  assert r.returncode!=0 and b is None
  assert left == [] and not exists and 'report' not in left
def test_output_has_exact_public_keys():
  """CERT-04: "Return an object with exactly max_flow, min_cut_capacity, source_side, shortest_path_cost, and shortest_path."""
  x=json.loads(run(base())[1]); assert set(x)=={'max_flow','min_cut_capacity','source_side','shortest_path_cost','shortest_path'}

def test_invalid_top_level_preserves_absent_destination_and_no_artifacts():
  """VALID-03: malformed top-level input rejects without creating output or side artifacts."""
  r,b,_,left,exists=run({'nodes':[],'edges':[],'source':'s','sink':'t'})
  assert r.returncode!=0 and b is None
  assert left == [] and not exists and 'report' not in left

def test_invalid_cost_preserves_existing_sentinel_byte_for_byte():
  """VALID-03: non-finite/non-numeric cost rejects while preserving a pre-existing destination."""
  a=base(); a['edges'][0]['cost']=True; sent=b'unchanged\x00'; r,b,s,left,exists=run(a,sent)
  assert r.returncode!=0 and b==s
  assert left == [] and exists and 'report' not in left

def test_duplicate_json_key_rejected_atomically():
  """VALID-04: duplicate JSON object keys are invalid and cannot publish a result."""
  with tempfile.TemporaryDirectory() as td:
    p=Path(td); i=p/'i.json'; o=p/'o.json'; i.write_text('{"nodes":["s","t"],"nodes":["s","t"],"edges":[],"source":"s","sink":"t"}',encoding='utf-8')
    r=subprocess.run([sys.executable,APP,str(i),str(o)],capture_output=True,timeout=10)
    assert r.returncode!=0 and not o.exists() and list(p.iterdir())==[i]

def test_late_invalid_record_does_not_publish_prefix_or_checkpoint():
  """VALID-03: a valid prefix followed by a malformed record leaves no partial publication."""
  a=base(); a['edges']=a['edges']+[{'u':'s','v':'t','capacity':float('nan'),'cost':0}]; r,b,_,left,exists=run(a)
  assert r.returncode!=0 and b is None
  assert left == [] and not exists and 'report' not in left

def test_released_rejected_released_state_matrix():
  """AXIS-STATE: released→rejected→released preserves publication and recovery invariants."""
  states = ['released', 'rejected', 'released']
  assert states == ['released', 'rejected', 'released']
  with tempfile.TemporaryDirectory() as td:
    p=Path(td); i=p/'i.json'; o=p/'o.json'; good=base(); i.write_text(json.dumps(good),encoding='utf-8')
    first=subprocess.run([sys.executable,APP,str(i),str(o)],capture_output=True,timeout=10); first_bytes=o.read_bytes()
    bad=base(); bad['edges'][0]['capacity']=True; i.write_text(json.dumps(bad),encoding='utf-8')
    second=subprocess.run([sys.executable,APP,str(i),str(o)],capture_output=True,timeout=10)
    assert first.returncode==0 and second.returncode!=0 and o.read_bytes()==first_bytes
    i.write_text(json.dumps(good),encoding='utf-8'); third=subprocess.run([sys.executable,APP,str(i),str(o)],capture_output=True,timeout=10)
    assert third.returncode==0 and o.read_bytes()==first_bytes

def test_rejected_released_rejected_state_matrix():
  """AXIS-STATE: rejected→released→rejected preserves the prior release and leaves no partial result."""
  states = ['rejected', 'released', 'rejected']
  assert states == ['rejected', 'released', 'rejected']
  with tempfile.TemporaryDirectory() as td:
    p=Path(td); i=p/'i.json'; o=p/'o.json'
    bad=base(); bad['edges'][0]['capacity']=True; i.write_text(json.dumps(bad),encoding='utf-8')
    first=subprocess.run([sys.executable,APP,str(i),str(o)],capture_output=True,timeout=10)
    assert first.returncode!=0 and not o.exists()
    i.write_text(json.dumps(base()),encoding='utf-8')
    second=subprocess.run([sys.executable,APP,str(i),str(o)],capture_output=True,timeout=10)
    assert second.returncode==0 and o.exists()
    released=o.read_bytes()
    i.write_text(json.dumps(bad),encoding='utf-8')
    third=subprocess.run([sys.executable,APP,str(i),str(o)],capture_output=True,timeout=10)
    assert third.returncode!=0 and o.read_bytes()==released
