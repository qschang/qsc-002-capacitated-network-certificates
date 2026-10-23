import importlib.util, json, os, subprocess, sys, tempfile, time
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
APP=os.environ.get('APP','/app/solve.py')
def run(d, sentinel=None):
  with tempfile.TemporaryDirectory() as td:
    p=Path(td); i=p/'i.json'; o=p/'o.json'; i.write_text(json.dumps(d),encoding='utf-8')
    if sentinel is not None:o.write_bytes(sentinel)
    r=subprocess.run([sys.executable,APP,str(i),str(o)],capture_output=True,timeout=10)
    leftovers=[q.name for q in p.iterdir() if q.name != 'i.json' and q.name != 'o.json']
    return r,(o.read_bytes() if o.exists() else None),sentinel,leftovers,o.exists()
def run_raw(raw, sentinel=None):
  with tempfile.TemporaryDirectory() as td:
    p=Path(td); i=p/'i.json'; o=p/'o.json'; i.write_text(raw,encoding='utf-8')
    if sentinel is not None:o.write_bytes(sentinel)
    r=subprocess.run([sys.executable,APP,str(i),str(o)],capture_output=True,timeout=10)
    leftovers=[q.name for q in p.iterdir() if q.name != 'i.json' and q.name != 'o.json']
    return r,(o.read_bytes() if o.exists() else None),sentinel,leftovers,o.exists()
def base(): return {'nodes':['s','a','b','t'],'edges':[{'u':'s','v':'a','capacity':3,'cost':2},{'u':'s','v':'a','capacity':2,'cost':1},{'u':'a','v':'t','capacity':4,'cost':2},{'u':'s','v':'b','capacity':5,'cost':1},{'u':'b','v':'t','capacity':5,'cost':3}], 'source':'s','sink':'t'}
def test_parallel_edges_and_cut_certificate():
  '''AXIS-FLOW: "允许平行边和自环。" and the cut certificate.'''
  r,b,_,left,exists=run(base()); assert r.returncode==0; x=json.loads(b); assert abs(x['max_flow']-9)<1e-12 and abs(x['max_flow']-x['min_cut_capacity'])<1e-12; assert left==[] and exists

def test_residual_rerouting_reaches_maximum_flow():
  '''FLOW-02: "正确计算有向多重图的最大流与最小割证书"'''
  a={'nodes':['s','a','b','x','y','t'],'source':'s','sink':'t','edges':[
    {'u':'s','v':'a','capacity':1,'cost':0},{'u':'s','v':'b','capacity':1,'cost':0},
    {'u':'a','v':'x','capacity':1,'cost':0},{'u':'a','v':'y','capacity':1,'cost':0},
    {'u':'b','v':'x','capacity':1,'cost':0},{'u':'x','v':'t','capacity':1,'cost':0},
    {'u':'y','v':'t','capacity':1,'cost':0}]}
  x=json.loads(run(a)[1]); assert x['max_flow']==2 and x['min_cut_capacity']==2 and x['source_side']==['s']
def test_self_loop_is_neutral_to_flow_and_path():
  '''FLOW-01: "允许平行边和自环。"'''
  a=base(); a['edges'].append({'u':'a','v':'a','capacity':100,'cost':0}); x=json.loads(run(a)[1]); assert x['max_flow']==9 and x['shortest_path_cost']==3 and x['shortest_path']==['s','a','t']

def test_rejects_reachable_negative_cost_self_loop_atomically():
  '''PATH-01: "负成本正容量自环是可达负成本环，因此必须拒收。"'''
  a={'nodes':['s','a','t'],'source':'s','sink':'t','edges':[
    {'u':'s','v':'a','capacity':1,'cost':0},{'u':'a','v':'a','capacity':1,'cost':-0.25},
    {'u':'a','v':'t','capacity':1,'cost':0}]}
  r,b,_,left,exists=run(a); assert r.returncode!=0 and b is None
  assert left==[] and not exists
  r,b,s,left,exists=run(a,b'prior-certificate'); assert r.returncode!=0 and b==s
  assert left==[] and exists
def test_negative_cost_path_and_lexicographic_tie_break():
  '''AXIS-PATH: "没有可达负成本环时，负成本边是合法输入；"'''
  a=base(); a['edges']=[{'u':'s','v':'b','capacity':1,'cost':-1},{'u':'b','v':'t','capacity':1,'cost':2},{'u':'s','v':'a','capacity':1,'cost':0},{'u':'a','v':'t','capacity':1,'cost':1}]; x=json.loads(run(a)[1]); assert x['shortest_path_cost']==1 and x['shortest_path']==['s','a','t']
def test_unreachable_sink_returns_null_certificates():
  '''PATH-02: "若 `sink` 不可达，两者都使用 `null`。"'''
  a=base(); a['edges']=[]; x=json.loads(run(a)[1]); assert x['shortest_path'] is None and x['shortest_path_cost'] is None
def test_rejects_negative_cycle_atomically():
  '''AXIS-REJECTION: "若在从 `source` 沿正容量边可达的子图中存在负成本环，则输入无效。"'''
  a=base(); a['edges'] += [{'u':'s','v':'a','capacity':1,'cost':0},{'u':'a','v':'s','capacity':1,'cost':-2}]; r,b,_,left,exists=run(a)
  assert r.returncode!=0 and b is None
  assert left == [] and not exists and 'report' not in left
  r,b,s,left,exists=run(a,b'old-certificate'); assert r.returncode!=0 and b==s
  assert left==[] and exists and 'report' not in left

def test_rejects_source_reachable_cycle_disconnected_from_sink():
  '''PATH-02: "若在从 `source` 沿正容量边可达的子图中存在负成本环，则输入无效。"'''
  a={'nodes':['s','a','b','t'],'source':'s','sink':'t','edges':[
    {'u':'s','v':'a','capacity':1,'cost':0},{'u':'a','v':'b','capacity':1,'cost':0},
    {'u':'b','v':'a','capacity':1,'cost':-1},{'u':'s','v':'t','capacity':1,'cost':2}]}
  r,b,_,left,exists=run(a,b'old-certificate'); assert r.returncode!=0 and b==b'old-certificate'
  assert left==[] and exists
  r,b,_,left,exists=run(a); assert r.returncode!=0 and b is None
  assert left==[] and not exists

def test_ignores_negative_cycle_without_positive_capacity_access():
  '''PATH-02: "容量为零的边不参与供给或路线计算。"'''
  a=base(); a['nodes'] += ['x','y']; a['edges'] += [
    {'u':'s','v':'x','capacity':0,'cost':0},{'u':'x','v':'y','capacity':1,'cost':-2},
    {'u':'y','v':'x','capacity':1,'cost':1}]
  x=json.loads(run(a)[1]); assert x['max_flow']==9 and x['min_cut_capacity']==9
  assert x['shortest_path_cost']==3 and x['shortest_path']==['s','a','t']
def test_late_invalid_edge_preserves_sentinel():
  '''VALID-03: "且不得创建或修改目标文件。"'''
  a=base(); a['edges'].append({'u':'x','v':'t','capacity':1,'cost':0}); sent=b'keep'; r,b,s,left,exists=run(a,sent)
  assert r.returncode!=0 and b==s
  assert left == [] and exists and 'report' not in left
  r,b,_,left,exists=run(a); assert r.returncode!=0 and b is None
  assert left==[] and not exists and 'report' not in left
def test_node_order_only_changes_sorted_projection():
  '''AXIS-CERTIFICATE: "并按输入节点顺序排列。"'''
  a=base(); b=dict(a); b['nodes']=['t','b','a','s']; x=json.loads(run(a)[1]); y=json.loads(run(b)[1]); assert x['max_flow']==y['max_flow'] and y['source_side']==['a','s']
def test_flow_cut_values_match_on_disconnected_components():
  '''CERT-04: "两者必须满足相对误差 `1e-9`、绝对误差 `1e-12` 的容差要求。"'''
  a=base(); a['nodes'] += ['z']; x=json.loads(run(a)[1]); assert x['max_flow']==x['min_cut_capacity']
def test_zero_capacity_edges_are_ignored():
  '''FLOW-01: "容量为零的边不参与供给或路线计算。"'''
  a=base(); a['edges'].append({'u':'s','v':'t','capacity':0,'cost':-10}); x=json.loads(run(a)[1]); assert x['max_flow']==9 and x['min_cut_capacity']==9 and x['shortest_path_cost']==3

def test_arbitrarily_small_positive_capacity_contributes_to_flow_and_path():
  '''FLOW-04: "任何大于零的有限容量都参与计算，不设正容量阈值。"'''
  a={'nodes':['s','t'],'source':'s','sink':'t','edges':[{'u':'s','v':'t','capacity':1e-16,'cost':-2}]}
  r,b,_,left,exists=run(a); x=json.loads(b)
  assert r.returncode==0 and x['max_flow']==1e-16 and x['min_cut_capacity']==1e-16
  assert x['source_side']==['s'] and x['shortest_path_cost']==-2 and x['shortest_path']==['s','t']
  assert left==[] and exists

def test_tiny_positive_capacity_exposes_reachable_negative_cycle():
  '''PATH-04: "沿任何正容量边可达" applies even when capacity is below 1e-12.'''
  a={'nodes':['s','a','b','t'],'source':'s','sink':'t','edges':[
    {'u':'s','v':'t','capacity':1,'cost':0},{'u':'s','v':'a','capacity':1e-16,'cost':0},
    {'u':'a','v':'b','capacity':1,'cost':-2},{'u':'b','v':'a','capacity':1,'cost':1}]}
  r,b,_,left,exists=run(a,b'previous'); assert r.returncode!=0 and b==b'previous'
  assert left==[] and exists

def test_large_network_meets_published_scale():
  '''PATH-03: "程序至少应在该规模的网络上于 20 秒内完成，并按上述规则生成完整结果。"'''
  layers=[[f'L{level:04d}{label}' for label in 'AB'] for level in range(1023)]
  nodes=['S']+[node for layer in layers for node in layer]+['T']; forward=[]
  forward += [{'u':'S','v':node,'capacity':1,'cost':-1} for node in layers[0]]
  for level,(previous,current) in enumerate(zip(layers,layers[1:])):
    cost=-1 if (level+1)%4==0 else 0
    forward += [{'u':u,'v':v,'capacity':1,'cost':cost} for u in previous for v in current for _ in range(4)]
  forward += [{'u':node,'v':'T','capacity':1,'cost':0} for node in layers[-1] for _ in range(15)]
  edges=list(reversed(forward))
  assert len(nodes)==2048 and len(edges)==16384
  with tempfile.TemporaryDirectory() as td:
    p=Path(td); i=p/'i.json'; o=p/'o.json'
    i.write_text(json.dumps({'nodes':nodes,'edges':edges,'source':'S','sink':'T'}),encoding='utf-8')
    started=time.monotonic(); r=subprocess.run([sys.executable,APP,str(i),str(o)],capture_output=True,timeout=20); elapsed=time.monotonic()-started
    assert r.returncode==0 and elapsed<20 and o.exists()
    x=json.loads(o.read_bytes())
    assert x['max_flow']==2 and x['min_cut_capacity']==2 and x['source_side']==['S']
    assert x['shortest_path_cost']==-256 and x['shortest_path']==['S']+[layer[0] for layer in layers]+['T']

def test_atomic_replace_failure_preserves_existing_destination():
  '''PUB-02: "发生任何内部错误时，程序必须以非零状态退出，且不得创建或修改目标文件。"'''
  with tempfile.TemporaryDirectory() as td:
    for label,sentinel in (('absent',None),('existing',b'previous-result\x00')):
      p=Path(td)/label; p.mkdir(); i=p/'i.json'; o=p/'o.json'; i.write_text(json.dumps(base()),encoding='utf-8')
      if sentinel is not None:o.write_bytes(sentinel)
      spec=importlib.util.spec_from_file_location('candidate_solver',APP); module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
      old_argv=sys.argv; original_replace=os.replace; sys.argv=[APP,str(i),str(o)]
      def fail_replace(_src,_dst): raise OSError('injected replace failure')
      try:
        module.os.replace=fail_replace
        with redirect_stderr(StringIO()): rc=module.main()
      finally:
        module.os.replace=original_replace; sys.argv=old_argv
      assert rc!=0
      if sentinel is None: assert not o.exists()
      else: assert o.read_bytes()==sentinel
      assert sorted(q.name for q in p.iterdir())==(['i.json'] if sentinel is None else ['i.json','o.json'])
def test_invalid_boolean_capacity_rejected():
  '''VALID-03: "布尔值不得当作数值。"'''
  a=base(); a['edges'][0]['capacity']=True; r,b,_,left,exists=run(a)
  assert r.returncode!=0 and b is None
  assert left == [] and not exists and 'report' not in left
  r,b,s,left,exists=run(a,b'keep'); assert r.returncode!=0 and b==s
  assert left==[] and exists and 'report' not in left
def test_output_has_exact_public_keys():
  '''CERT-04: "输出对象必须且只能包含 `max_flow`、`min_cut_capacity`、`source_side`、`shortest_path_cost` 和 `shortest_path` 五个字段。"'''
  x=json.loads(run(base())[1]); assert set(x)=={'max_flow','min_cut_capacity','source_side','shortest_path_cost','shortest_path'}

def test_invalid_top_level_preserves_absent_destination_and_no_artifacts():
  '''VALID-03: "输入结构、数值边界、路径与割证书、确定性排序、误差容差以及跨运行发布状态都属于公开契约的一部分。"'''
  r,b,_,left,exists=run({'nodes':[],'edges':[],'source':'s','sink':'t'})
  assert r.returncode!=0 and b is None
  assert left == [] and not exists and 'report' not in left
  r,b,s,left,exists=run({'nodes':[],'edges':[],'source':'s','sink':'t'},b'keep')
  assert r.returncode!=0 and b==s
  assert left==[] and exists and 'report' not in left

def test_invalid_cost_preserves_existing_sentinel_byte_for_byte():
  '''VALID-03: "所有数值都必须有限，布尔值不得当作数值。"'''
  a=base(); a['edges'][0]['cost']=True; sent=b'unchanged\x00'; r,b,s,left,exists=run(a,sent)
  assert r.returncode!=0 and b==s
  assert left == [] and exists and 'report' not in left
  r,b,_,left,exists=run(a); assert r.returncode!=0 and b is None
  assert left==[] and not exists and 'report' not in left

def test_duplicate_json_key_rejected_atomically():
  '''VALID-04: "任一 JSON 对象内同名键重复出现时，输入无效。"'''
  raw='{"nodes":["s","t"],"nodes":["s","t"],"edges":[],"source":"s","sink":"t"}'
  r,b,_,left,exists=run_raw(raw); assert r.returncode!=0 and b is None
  assert left==[] and not exists
  r,b,s,left,exists=run_raw(raw,b'unchanged\x00'); assert r.returncode!=0 and b==s
  assert left==[] and exists

def test_late_invalid_record_does_not_publish_prefix_or_checkpoint():
  '''VALID-03: "只有在校验和计算全部完成后，才允许发布合法结果。"'''
  a=base(); a['edges']=a['edges']+[{'u':'s','v':'t','capacity':float('nan'),'cost':0}]; r,b,_,left,exists=run(a)
  assert r.returncode!=0 and b is None
  assert left == [] and not exists and 'report' not in left
  r,b,s,left,exists=run(a,b'keep'); assert r.returncode!=0 and b==s
  assert left==[] and exists and 'report' not in left

def test_released_rejected_released_state_matrix():
  '''AXIS-STATE: "连续执行“发布、拒收、发布”时，必须始终保持上述保证。"'''
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
  '''AXIS-STATE: "连续执行“发布、拒收、发布”时，必须始终保持上述保证。"'''
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
