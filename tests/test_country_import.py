import sys,tempfile,json,zipfile,io
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'collector'))
import import_transitous_country as c
from unittest.mock import patch
html='<h4>Sample Transit</h4><a href="https://api.transitous.org/gtfs/us-test_Sample.gtfs.zip">Processed File</a><a href="https://example.com/not-a-feed.zip">Other</a>'
catalog=c.catalogue(html);assert len(catalog['countries']['US'])==1
assert c.catalogue('<h4>Unsafe</h4><a href="https://api.transitous.org/gtfs/../../bad.gtfs.zip">File</a>')['countries']=={}
with tempfile.TemporaryDirectory() as tmp:
 out=Path(tmp)/'out';prev=Path(tmp)/'prev';prev.mkdir()
 source=catalog['countries']['US'][0]
 old={**source,'status':'ready','fetched_at':'2026-10-01T00:00:00Z','sha256':'verified'}
 (prev/'index.json').write_text(json.dumps({'feeds':[old]}))
 with patch.object(c,'download',side_effect=ValueError('Invalid zip')):
  result=c.mirror('US',catalog,out,prev)
 assert result[0]['sha256']=='verified' and result[0]['status']=='ready'
 assert not (out/'feeds'/source['id']).exists()
 print('Country extraction, URL restrictions and preservation of last verified data passed.')

# A failed feed cannot starve pending sources; verified feeds rotate oldest first.
with tempfile.TemporaryDirectory() as tmp:
 prev=Path(tmp)/'prev';prev.mkdir();out=Path(tmp)/'out'
 sources=[{**source,'id':'us-'+str(i),'source_url':'https://api.transitous.org/gtfs/us-'+str(i)+'.gtfs.zip'} for i in range(22)]
 records=[{**sources[0],'status':'unavailable'}]+[{**s,'status':'pending'} for s in sources[1:]]
 (prev/'index.json').write_text(json.dumps({'feeds':records}))
 calls=[]
 def fail(url,limit):
  calls.append(url);raise ValueError('Unavailable')
 with patch.object(c,'download',side_effect=fail):c.mirror('US',{'countries':{'US':sources}},out,prev)
 assert len(calls)==20 and sources[0]['source_url'] not in calls
 records=[{**s,'status':'ready','fetched_at':f'2026-09-{i+1:02d}T00:00:00Z'} for i,s in enumerate(sources)]
 (prev/'index.json').write_text(json.dumps({'feeds':records}));calls=[]
 with patch.object(c,'download',side_effect=fail):c.mirror('US',{'countries':{'US':sources[::-1]}},out,prev)
 assert calls[0]==sources[0]['source_url']
 print('Pending sources progress and oldest verified snapshots refresh first.')

# Visitor-selected sources are attempted before a full batch of pending feeds.
with tempfile.TemporaryDirectory() as tmp:
 out=Path(tmp)/'out';calls=[]
 with patch.object(c,'download',side_effect=fail):c.mirror('US',{'countries':{'US':sources}},out,selected_source=sources[-1]['id'])
 assert calls[0]==sources[-1]['source_url'] and len(calls)==20
 try:c.mirror('US',{'countries':{'US':sources}},out,selected_source='mx_mexico')
 except ValueError:pass
 else:raise AssertionError('Cross-country selected source was accepted')
 print('Selected-source priority and country membership passed.')
