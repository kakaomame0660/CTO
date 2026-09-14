from __future__ import annotations
import json, re, shutil, subprocess, sys
from pathlib import Path
import numpy as np
import pandas as pd
import joblib
import lightgbm as lgb
from sklearn.metrics import ndcg_score

ROOT=Path.cwd(); OUT=ROOT/'artifacts'; OUT.mkdir(exist_ok=True)
K=ROOT/'kenseimk'; T=ROOT/'takeruts'
BANNED={'rank','agari','finish_type','margin','win_lose','ni_sha_tan','san_ren_tan','san_ren_fuku','wide','lineup','mark','mark_num','player_name'}

def sh(*cmd):
    subprocess.run(cmd,check=True)

def num(s): return pd.to_numeric(s,errors='coerce')
def gear_num(s): return pd.to_numeric(s.astype(str).str.extract(r'(\d+(?:\.\d+)?)',expand=False),errors='coerce')

def load_modern():
    files=[]
    for p in sorted((K/'keirin_data').glob('20??_??_keirin.csv')):
        m=re.match(r'(\d{4})_(\d{2})_keirin\.csv$',p.name)
        if not m: continue
        ym=int(m.group(1))*100+int(m.group(2))
        if 202401<=ym<=202608: files.append(p)
    dfs=[]
    keep=['race_id','venue_slug','date','race_no','banum','age','term','player_class','running_style','gear','race_score','rank','ni_sha_tan','san_ren_tan','san_ren_fuku']
    for p in files:
        hdr=pd.read_csv(p,nrows=0,encoding='utf-8-sig').columns.tolist()
        use=[c for c in keep if c in hdr]
        d=pd.read_csv(p,usecols=use,encoding='utf-8-sig',low_memory=False)
        d['source_file']=p.name; dfs.append(d)
    d=pd.concat(dfs,ignore_index=True)
    d['date']=pd.to_datetime(d['date'],errors='coerce')
    for c in ['race_no','banum','age','term','race_score','rank']:
        if c in d: d[c]=num(d[c])
    d['gear_num']=gear_num(d['gear']) if 'gear' in d else np.nan
    d=d[(d.date>='2024-01-01')&(d.date<='2026-08-31')].copy()
    d=d.dropna(subset=['race_id','date','banum','race_score','rank'])
    d=d[(d['rank']>=1)&(d['rank']<=9)]
    d=d.drop_duplicates(['race_id','banum'],keep='last')
    # Keep only races with exactly one winner and >=5 valid riders.
    g=d.groupby('race_id',sort=False)
    ok=g['rank'].agg(lambda x: (x.eq(1).sum()==1) and (len(x)>=5))
    d=d[d.race_id.isin(ok[ok].index)].copy()
    d['field_size']=d.groupby('race_id')['banum'].transform('size')
    d['score_mean']=d.groupby('race_id')['race_score'].transform('mean')
    d['score_std']=d.groupby('race_id')['race_score'].transform('std').replace(0,np.nan)
    d['score_max']=d.groupby('race_id')['race_score'].transform('max')
    d['score_z']=(d.race_score-d.score_mean)/d.score_std
    d['score_gap_top']=d.race_score-d.score_max
    d['score_rank']=d.groupby('race_id')['race_score'].rank(method='average',ascending=False)
    d['age_z']=(d.age-d.groupby('race_id')['age'].transform('mean'))/d.groupby('race_id')['age'].transform('std').replace(0,np.nan)
    d['relevance']=(d.field_size+1-d['rank']).clip(lower=0).astype(int)
    return d,files

def payout_value(s):
    if pd.isna(s): return np.nan
    m=re.search(r'([\d,]+)円',str(s)); return float(m.group(1).replace(',','')) if m else np.nan

def combo(s,n):
    if pd.isna(s): return None
    m=re.search(r'(\d(?:-\d){%d})'% (n-1),str(s)); return m.group(1) if m else None

def make_matrix(d, cats, numeric):
    x=d[numeric].copy()
    for c in numeric: x[c]=num(x[c])
    cat=pd.get_dummies(d[cats].fillna('UNK').astype(str),prefix=cats,dtype=np.int8) if cats else pd.DataFrame(index=d.index)
    x=pd.concat([x,cat],axis=1).replace([np.inf,-np.inf],np.nan).fillna(0)
    return x

def prep_splits(d, feature_cols=None):
    cats=['venue_slug','player_class','running_style']
    numeric=['banum','race_no','age','term','gear_num','race_score','field_size','score_z','score_gap_top','score_rank','age_z']
    x=make_matrix(d,cats,numeric)
    if feature_cols is not None: x=x.reindex(columns=feature_cols,fill_value=0)
    return x

def sorted_part(d,mask):
    q=d.loc[mask].copy().sort_values(['date','race_id','banum']).reset_index(drop=True)
    return q

def groups(q): return q.groupby('race_id',sort=False).size().tolist()

def eval_ranker(q,pred,label):
    q=q.copy(); q['pred']=pred
    n=len(q.race_id.unique()); wins=top1top3=0; nd=[]; overlap=[]
    bscore=0
    ret2=ret3=0.0; bet2=bet3=0
    for rid,g in q.groupby('race_id',sort=False):
        g=g.sort_values('banum')
        p=g.sort_values('pred',ascending=False)
        winner=g.loc[g['rank'].idxmin()]
        top=p.iloc[0]
        wins+=int(top['rank']==1); top1top3+=int(top['rank']<=3)
        b=g.sort_values('race_score',ascending=False).iloc[0]; bscore+=int(b['rank']==1)
        try: nd.append(float(ndcg_score([g.relevance.to_numpy()],[g.pred.to_numpy()],k=3)))
        except Exception: pass
        a=set(g.nsmallest(3,'rank').banum.astype(int)); pp=set(p.head(3).banum.astype(int)); overlap.append(len(a&pp)/3)
        if {'ni_sha_tan','san_ren_tan'}.issubset(g.columns):
            actual2='-'.join(map(str,g.nsmallest(2,'rank').sort_values('rank').banum.astype(int).tolist()))
            actual3='-'.join(map(str,g.nsmallest(3,'rank').sort_values('rank').banum.astype(int).tolist()))
            pred2='-'.join(map(str,p.head(2).banum.astype(int).tolist())); pred3='-'.join(map(str,p.head(3).banum.astype(int).tolist()))
            r=g.iloc[0]
            v2=payout_value(r.get('ni_sha_tan')); c2=combo(r.get('ni_sha_tan'),2)
            v3=payout_value(r.get('san_ren_tan')); c3=combo(r.get('san_ren_tan'),3)
            if np.isfinite(v2): bet2+=100; ret2 += v2 if pred2==actual2 and (c2 is None or c2==actual2) else 0
            if np.isfinite(v3): bet3+=100; ret3 += v3 if pred3==actual3 and (c3 is None or c3==actual3) else 0
    return {'label':label,'races':n,'top1_accuracy':wins/n if n else None,'top1_finish_top3':top1top3/n if n else None,
            'ndcg_at_3':float(np.mean(nd)) if nd else None,'top3_set_overlap':float(np.mean(overlap)) if overlap else None,
            'race_score_baseline_top1':bscore/n if n else None,
            'exact_2ren_single_point_roi':ret2/bet2 if bet2 else None,'exact_2ren_bets':bet2//100,
            'exact_3ren_single_point_roi':ret3/bet3 if bet3 else None,'exact_3ren_bets':bet3//100}

def train_modern(d):
    tr=sorted_part(d,d.date<='2025-12-31'); va=sorted_part(d,(d.date>='2026-01-01')&(d.date<='2026-06-30')); te=sorted_part(d,(d.date>='2026-07-01')&(d.date<='2026-08-31'))
    allx=prep_splits(pd.concat([tr,va,te],ignore_index=True)); cols=list(allx.columns)
    Xtr=prep_splits(tr,cols); Xva=prep_splits(va,cols); Xte=prep_splits(te,cols)
    model=lgb.LGBMRanker(objective='lambdarank',metric='ndcg',n_estimators=800,learning_rate=.03,num_leaves=31,
        min_child_samples=40,subsample=.9,colsample_bytree=.85,reg_lambda=1.0,random_state=20260914,n_jobs=-1,verbosity=-1)
    model.fit(Xtr,tr.relevance,group=groups(tr),eval_set=[(Xva,va.relevance)],eval_group=[groups(va)],eval_at=[1,3],callbacks=[lgb.early_stopping(60,verbose=False)])
    pva=model.predict(Xva,num_iteration=model.best_iteration_); pte=model.predict(Xte,num_iteration=model.best_iteration_)
    return model,cols,tr,va,te,eval_ranker(va,pva,'validation_2026H1'),eval_ranker(te,pte,'holdout_2026_07_08')

def load_old():
    dfs=[]
    for p in sorted((T/'data').glob('*_train_data.csv')):
        try: d=pd.read_csv(p,low_memory=False)
        except Exception: continue
        needed={'date','race_num','car_num','age','period','gear','racing piont','result'}
        if not needed.issubset(d.columns): continue
        d=d.copy(); d['venue_slug']=d.get('place',p.stem.replace('_train_data',''))
        d['date']=pd.to_datetime(d['date'].astype(str),format='%Y%m%d',errors='coerce')
        d['race_no']=num(d['race_num']); d['banum']=num(d['car_num']); d['age']=num(d['age']); d['term']=num(d['period']); d['gear_num']=gear_num(d['gear']); d['race_score']=num(d['racing piont']); d['rank']=num(d['result'])
        d['race_id']='old_'+d.date.dt.strftime('%Y%m%d')+'_'+d.venue_slug.astype(str)+'_'+d.race_no.fillna(0).astype(int).astype(str)
        dfs.append(d[['race_id','venue_slug','date','race_no','banum','age','term','gear_num','race_score','rank']])
    if not dfs: return pd.DataFrame()
    d=pd.concat(dfs,ignore_index=True).dropna(subset=['date','banum','race_score','rank'])
    d=d[(d['rank']>=1)&(d['rank']<=9)].drop_duplicates(['race_id','banum'])
    ok=d.groupby('race_id')['rank'].agg(lambda x:(x.eq(1).sum()==1) and len(x)>=5); d=d[d.race_id.isin(ok[ok].index)].copy()
    d['field_size']=d.groupby('race_id').banum.transform('size'); d['score_mean']=d.groupby('race_id').race_score.transform('mean'); d['score_std']=d.groupby('race_id').race_score.transform('std').replace(0,np.nan); d['score_max']=d.groupby('race_id').race_score.transform('max')
    d['score_z']=(d.race_score-d.score_mean)/d.score_std; d['score_gap_top']=d.race_score-d.score_max; d['score_rank']=d.groupby('race_id').race_score.rank(method='average',ascending=False); d['age_z']=(d.age-d.groupby('race_id').age.transform('mean')/d.groupby('race_id').age.transform('std').replace(0,np.nan)); d['relevance']=(d.field_size+1-d['rank']).clip(lower=0).astype(int)
    return d

def train_aux(old,modern,holdout,cols):
    if old.empty: return None,None
    m=sorted_part(modern,modern.date<='2025-12-31'); o=old.sort_values(['date','race_id','banum']).reset_index(drop=True)
    common=['banum','race_no','age','term','gear_num','race_score','field_size','score_z','score_gap_top','score_rank','age_z']
    both=pd.concat([o,m],ignore_index=True,sort=False); X=make_matrix(both,['venue_slug'],common); hX=make_matrix(holdout,['venue_slug'],common).reindex(columns=X.columns,fill_value=0)
    w=np.r_[np.full(len(o),0.15),np.ones(len(m))]
    model=lgb.LGBMRanker(objective='lambdarank',metric='ndcg',n_estimators=500,learning_rate=.035,num_leaves=31,min_child_samples=50,reg_lambda=1.2,random_state=20260914,n_jobs=-1,verbosity=-1)
    model.fit(X,both.relevance,group=groups(both),sample_weight=w)
    pred=model.predict(hX); return model,eval_ranker(holdout,pred,'holdout_old_plus_modern')

def main():
    if K.exists(): shutil.rmtree(K)
    if T.exists(): shutil.rmtree(T)
    sh('git','clone','--depth','1','https://github.com/Kenseimk/keirin-data.git',str(K))
    sh('git','clone','--depth','1','https://github.com/takeruts/keirin_ai.git',str(T))
    modern,files=load_modern()
    audit={'files':len(files),'rows':int(len(modern)),'races':int(modern.race_id.nunique()),'venues':int(modern.venue_slug.nunique()),'date_min':str(modern.date.min().date()),'date_max':str(modern.date.max().date()),'duplicate_rider_keys':int(modern.duplicated(['race_id','banum']).sum()),'banned_feature_columns':sorted(BANNED),'holdout_rule':'2026-07-01..2026-08-31 untouched until final evaluation','september_2026_used':False}
    model,cols,tr,va,te,mva,mte=train_modern(modern)
    joblib.dump({'model':model,'feature_columns':cols,'trained_through':'2025-12-31','validation':'2026H1','holdout':'2026-07..08'},OUT/'modern_ranker.joblib',compress=3)
    old=load_old(); aux_model,aux_metric=train_aux(old,modern,te,cols)
    if aux_model is not None: joblib.dump({'model':aux_model,'note':'2008-2018 auxiliary weight 0.15 + modern through 2025'},OUT/'old_aux_ranker.joblib',compress=3)
    chosen='modern_ranker'
    if aux_metric and aux_metric['ndcg_at_3']>mte['ndcg_at_3'] and aux_metric['top1_accuracy']>=mte['top1_accuracy']-0.005: chosen='old_aux_ranker'
    imp=sorted(zip(cols,model.feature_importances_.tolist()),key=lambda z:z[1],reverse=True)[:25]
    report={'data_audit':audit,'split_races':{'train':int(tr.race_id.nunique()),'validation':int(va.race_id.nunique()),'holdout':int(te.race_id.nunique())},'split_rows':{'train':len(tr),'validation':len(va),'holdout':len(te)},'modern_validation':mva,'modern_holdout':mte,'takeruts_old':{'rows':int(len(old)),'races':int(old.race_id.nunique()) if len(old) else 0,'date_min':str(old.date.min().date()) if len(old) else None,'date_max':str(old.date.max().date()) if len(old) else None,'weight':0.15,'holdout_metric':aux_metric},'selected_variant':chosen,'best_iteration':int(model.best_iteration_ or model.n_estimators),'top_feature_importance':imp,'notes':['No post-race rank/agari/finish/margin/payout columns are used as model features.','Kenseimk 2026-09 is excluded completely.','Payout ROI is only a fixed 1-point diagnostic, not an EV/closing-odds strategy.','haruqube db/keirin.db is not in its GitHub repository and therefore is not included in training.']}
    (OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['# KEIRIN Historical Training Report','',f"Modern data: {audit['date_min']} to {audit['date_max']} / {audit['races']:,} races / {audit['rows']:,} rider rows",f"Split races: train {report['split_races']['train']:,}, validation {report['split_races']['validation']:,}, holdout {report['split_races']['holdout']:,}",'', '## Modern holdout (2026-07..08)']
    for k,v in mte.items(): lines.append(f'- {k}: {v}')
    lines += ['', '## Old-data auxiliary holdout']
    if aux_metric:
        for k,v in aux_metric.items(): lines.append(f'- {k}: {v}')
    lines += ['',f'**Selected variant: {chosen}**','', '2026-09 data was NOT used. Post-race outcome/payout columns were excluded from features.']
    (OUT/'report.md').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__': main()
