"""Publish public IndexNow verification files and the deployed Git revision."""
import json,os,pathlib,re,sys
root=pathlib.Path(__file__).resolve().parent
config=json.loads((root/'sites.json').read_text())
out=pathlib.Path(sys.argv[1]);out.mkdir(parents=True,exist_ok=True)
for site in config['sites']:
 key=site['key']
 if not re.fullmatch(r'[A-Za-z0-9-]{8,128}',key): raise ValueError('Invalid public verification key')
 (out/(key+'.txt')).write_text(key+'\n',encoding='utf-8')
sha=os.getenv('VERCEL_GIT_COMMIT_SHA','')
(out/'indexnow-deployment.json').write_text(json.dumps({'projectId':config['sites'][0]['projectId'],'sha':sha}),encoding='utf-8')
