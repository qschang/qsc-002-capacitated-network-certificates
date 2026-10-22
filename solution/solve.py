#!/usr/bin/env python3
from __future__ import annotations
import json, math, os, sys, tempfile

def finite(x): return isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x)
def reject(message): raise ValueError(message)
def read_input(path):
    with open(path,encoding='utf-8') as f: value=json.load(f)
    if not isinstance(value,dict) or set(value)!={'nodes','edges','source','sink'}: reject('top-level schema')
    return value
def validate(value):
    nodes,raw,source,sink=value['nodes'],value['edges'],value['source'],value['sink']
    if not isinstance(nodes,list) or not nodes or any(not isinstance(x,str) or not x for x in nodes) or len(set(nodes))!=len(nodes): reject('nodes')
    if not isinstance(raw,list) or source not in nodes or sink not in nodes or source==sink: reject('terminals')
    idx={x:i for i,x in enumerate(nodes)}; edges=[]
    for e in raw:
        if not isinstance(e,dict) or set(e)!={'u','v','capacity','cost'}: reject('edge keys')
        if e['u'] not in idx or e['v'] not in idx or not finite(e['capacity']) or e['capacity']<0 or not finite(e['cost']): reject('edge values')
        edges.append((idx[e['u']],idx[e['v']],float(e['capacity']),float(e['cost'])))
    return nodes,idx[source],idx[sink],edges
def flow_cut(n,s,t,edges):
    g=[[] for _ in range(n)]
    for k,(u,v,c,_w) in enumerate(edges):
        if u == v:
            continue
        a=[v,c,None,k]; b=[u,0.0,a,-1]; a[2]=b; g[u].append(a); g[v].append(b)
    total=0.0
    while True:
        p=[None]*n; p[s]=(-1,None); q=[s]
        for u in q:
            for a in g[u]:
                if a[1]>1e-12 and p[a[0]] is None: p[a[0]]=(u,a); q.append(a[0])
        if p[t] is None: break
        z=float('inf'); v=t
        while v!=s: u,a=p[v]; z=min(z,a[1]); v=u
        v=t
        while v!=s: u,a=p[v]; a[1]-=z; a[2][1]+=z; v=u
        total+=z
    reach={s}; q=[s]
    for u in q:
        for a in g[u]:
            if a[1]>1e-12 and a[0] not in reach: reach.add(a[0]); q.append(a[0])
    cut=sum(c for u,v,c,_w in edges if u in reach and v not in reach)
    return total,reach,cut
def shortest(nodes,s,t,edges):
    n=len(nodes); d=[float('inf')]*n; d[s]=0.0
    for _ in range(n-1):
        changed=False
        for u,v,_c,w in edges:
            if u == v:
                continue
            if d[u]!=float('inf') and d[v]>d[u]+w+1e-15: d[v]=d[u]+w; changed=True
        if not changed: break
    for u,v,_c,w in edges:
        if u == v:
            continue
        if d[u]!=float('inf') and d[v]>d[u]+w+1e-12: reject('reachable negative cycle')
    best=None
    def visit(u,path,cost):
        nonlocal best
        if u==t:
            cand=(cost,tuple(nodes[i] for i in path)); best=cand if best is None or cand<best else best; return
        for a,b,_c,w in edges:
            if a == b:
                continue
            if a==u and b not in path: visit(b,path+[b],cost+w)
    visit(s,[s],0.0)
    return (None,None) if best is None else (best[0],list(best[1]))
def compute(value):
    nodes,s,t,edges=validate(value); mf,reach,cut=flow_cut(len(nodes),s,t,edges)
    if abs(mf-cut)>1e-9*max(1.0,abs(cut))+1e-12: reject('flow cut mismatch')
    pc,path=shortest(nodes,s,t,edges)
    return {'max_flow':mf,'min_cut_capacity':cut,'source_side':[nodes[i] for i in range(len(nodes)) if i in reach],'shortest_path_cost':pc,'shortest_path':path}
def main():
    if len(sys.argv)!=3: return 2
    tmp=None
    try:
        out=compute(read_input(sys.argv[1])); dst=os.path.abspath(sys.argv[2]); fd,tmp=tempfile.mkstemp(prefix='.network-certificate-',dir=os.path.dirname(dst) or '.')
        with os.fdopen(fd,'w',encoding='utf-8') as f: json.dump(out,f,separators=(',',':'),allow_nan=False); f.write('\n'); f.flush(); os.fsync(f.fileno())
        os.replace(tmp,dst); tmp=None; return 0
    except Exception as exc:
        if tmp and os.path.exists(tmp): os.unlink(tmp)
        print(str(exc),file=sys.stderr); return 1
if __name__=='__main__': raise SystemExit(main())
