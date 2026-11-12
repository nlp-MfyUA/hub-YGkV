// Execute the actual frontend script against a minimal DOM and HTTP test doubles.
// This checks interaction logic, not browser layout or a real service integration.
const fs=require('node:fs');
const vm=require('node:vm');
const assert=require('node:assert/strict');
class Element{
  constructor(tag){this.tag=tag;this.children=[];this.files=[];this.value='';this.disabled=false;this.text='';}
  set textContent(value){this.text=value;this.children=[];}
  get textContent(){return this.text+this.children.map(x=>x.textContent||'').join('');}
  set innerHTML(value){throw Error('Unsafe innerHTML use');}
  append(...elements){this.children.push(...elements);}
  replaceChildren(...elements){this.children=elements;this.text='';}
}
class FormData{constructor(){this.items=[];}append(key,value){this.items.push([key,value]);}}
(async()=>{
  const ids=Object.fromEntries(['pdfs','upload','docs','question','image','session','ask','answer','notice'].map(x=>[x,new Element(x)]));
  let docs=[{id:'one',name:'<img src=x onerror=alert(1)>.pdf',status:'ready',error:''},
    {id:'two',name:'failed.pdf',status:'failed',error:'parser failed'}];
  const calls=[];
  const fetch=async(url,options={})=>{
    calls.push({url,options});let status=200,body;
    if(url==='/documents'&&options.method==='POST'){
      assert.equal(options.body.items.filter(x=>x[0]==='files').length,2);
      docs.push({id:'three',name:'new.pdf',status:'queued',error:''});body={document_ids:['three']};
    }else if(url==='/documents')body=docs;
    else if(url==='/documents/two/retry'){docs[1].status='queued';docs[1].error='';body={status:'queued'};}
    else if(url==='/chat'){
      const form=options.body.items;
      assert.equal(form.find(x=>x[0]==='question')[1],'请比较两张图片');
      assert.equal(form.find(x=>x[0]==='session_id')[1],'demo-session');
      assert.equal(form.find(x=>x[0]==='image')[1].name,'query.png');
      body={blocks:[{type:'text',text:'说明[S1] <script>alert(1)</script>'},
        {type:'image',source_id:'S1',url:'/media/known.jpg'},{type:'text',text:'后续解释'}],
        sources:{S1:{name:'paper.pdf',page:2,pdf:'/documents/one/pdf#page=2'}}};
    }else{status=404;body={detail:'not found'};}
    return {ok:status<400,json:async()=>JSON.parse(JSON.stringify(body))};
  };
  const script=fs.readFileSync(__dirname+'/app.html','utf8').match(/<script>([\s\S]*?)<\/script>/)[1];
  const context=vm.createContext({document:{getElementById:x=>ids[x],createElement:x=>new Element(x)},
    fetch,FormData,setTimeout:()=>0,console});
  await vm.runInContext(script,context);
  assert.equal(ids.docs.children.length,2);
  assert.ok(ids.docs.textContent.includes('<img src=x onerror=alert(1)>.pdf'));
  const retry=ids.docs.children[1].children.find(x=>x.tag==='button');
  await retry.onclick();assert.equal(docs[1].status,'queued');
  ids.pdfs.files=[{name:'a.pdf'},{name:'b.pdf'}];await ids.upload.onclick();
  assert.equal(ids.docs.children.length,3);assert.equal(ids.upload.disabled,false);
  ids.question.value='请比较两张图片';ids.session.value='demo-session';ids.image.files=[{name:'query.png'}];await ids.ask.onclick();
  assert.equal(ids.answer.children.map(x=>x.tag).join(','),'p,figure,p,p');
  assert.equal(ids.answer.children[1].children[0].src,'/media/known.jpg');
  assert.ok(ids.answer.textContent.includes('<script>alert(1)</script>'));
  assert.equal(ids.ask.disabled,false);assert.equal(ids.notice.textContent,'');
  ids.pdfs.files=[];await ids.upload.onclick();assert.equal(ids.notice.textContent,'请先选择 PDF。');
  console.log('Frontend interaction checks passed (DOM/HTTP doubles; no browser layout check).');
})().catch(error=>{console.error(error);process.exit(1)});
