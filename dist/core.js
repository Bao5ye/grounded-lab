export const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const uid=prefix=>prefix+'-'+(globalThis.crypto?.randomUUID?.()||Date.now().toString(36)+Math.random().toString(36).slice(2,8));
export function splitText(text){return String(text).replace(/\r\n/g,'\n').split(/\n\s*\n/).map(x=>x.trim()).filter(Boolean).flatMap(p=>{if(p.length<=1600)return[p];const out=[];for(let i=0;i<p.length;i+=1400)out.push(p.slice(i,i+1400));return out;});}
export function validateState(s){
 if(!s||s.schema!=='grounded-lab-v1'||!s.project||typeof s.project.title!=='string'||!s.core||!Array.isArray(s.core.alternatives))throw Error('请选择本工作台导出的项目 JSON 文件。');
 for(const k of ['sources','evidence','codes','categories','relations','sampling','memos','audit'])if(!Array.isArray(s[k]))throw Error('项目文件缺少 '+k+' 数据。');
 const ids=list=>{const set=new Set();for(const item of list){if(!item||typeof item.id!=='string'||!item.id||set.has(item.id))throw Error('项目中存在缺失或重复的标识。');set.add(item.id);}return set;};
 const ss=ids(s.sources),ee=ids(s.evidence),cc=ids(s.categories);ids(s.codes);ids(s.relations);ids(s.sampling);ids(s.memos);
 const strings=(item,keys)=>keys.every(k=>typeof item?.[k]==='string');
 if(!strings(s.project,['title','motivation','question','population','unit','boundary','assumptions'])||!strings(s.core,['selected','story'])||s.core.alternatives.some(v=>typeof v!=='string'))throw Error('研究意图或理论故事线格式不完整。');
 if(s.sources.some(v=>!strings(v,['name','kind','participant','date','role','status'])||typeof v.included!=='boolean'||typeof v.demo!=='boolean'))throw Error('原始资料信息不完整。');
 if(s.evidence.some(v=>!strings(v,['text','position','speaker','sourceId'])))throw Error('原始证据格式不完整。');
 if(s.codes.some(v=>!strings(v,['name','definition','categoryId','quote','rationale','origin'])))throw Error('概念编码格式不完整。');
 if(s.categories.some(v=>!strings(v,['name','type','description'])||!Array.isArray(v.properties)||v.properties.some(p=>typeof p!=='string')))throw Error('范畴定义格式不完整。');
 if(s.relations.some(v=>!strings(v,['from','to','label','caution'])))throw Error('范畴关系格式不完整。');
 if(s.sampling.some(v=>!strings(v,['title','reason','question'])||typeof v.done!=='boolean')||s.memos.some(v=>!strings(v,['title','type','text','evidenceId','date'])||(v.evidenceId&&!ee.has(v.evidenceId))))throw Error('抽样任务或备忘录格式不完整。');
 if(s.audit.some(v=>!strings(v,['time','action','detail'])||!Number.isFinite(Date.parse(v.time))))throw Error('操作记录格式不完整。');
 if(s.evidence.some(e=>!ss.has(e.sourceId)||typeof e.text!=='string'))throw Error('资料与证据的关联不完整。');
 for(const c of s.codes)if(typeof c.name!=='string'||typeof c.definition!=='string'||!Array.isArray(c.evidenceIds)||c.evidenceIds.some(id=>!ee.has(id))||(c.categoryId&&!cc.has(c.categoryId))||!['pending','confirmed','rejected'].includes(c.status))throw Error('编码与证据的关联不完整。');
 for(const c of s.categories)if((c.parentId && (!cc.has(c.parentId)||c.parentId===c.id))||!Array.isArray(c.properties)||!Array.isArray(c.evidenceIds)||c.evidenceIds.some(id=>!ee.has(id)))throw Error('范畴资料不完整。');
 for(const r of s.relations)if(!cc.has(r.from)||!cc.has(r.to)||!Array.isArray(r.evidenceIds)||r.evidenceIds.some(id=>!ee.has(id)))throw Error('范畴关系不完整。');return s;
}
export function quoteStatus(c,ev){return !!c.quote&&c.evidenceIds.some(id=>ev.find(e=>e.id===id)?.text.includes(c.quote));}
export function codingCSV(s){
 const rows=[['编码ID','概念','定义','子范畴','范畴','核心范畴候选','核心范畴状态','引文','证据ID','原始资料','位置','原始文本','编码状态','资料身份','编码来源','编码理由']];
 for(const c of s.codes)for(const eid of c.evidenceIds){const e=s.evidence.find(x=>x.id===eid);if(!e)continue;const src=s.sources.find(x=>x.id===e.sourceId),k=s.categories.find(x=>x.id===c.categoryId),parent=k?.parentId?s.categories.find(x=>x.id===k.parentId):null;
 rows.push([c.id,c.name,c.definition,k?.type==='子范畴'?k.name:'',parent?.name||(k?.type==='子范畴'?'未归类':k?.name)||'未归类',s.core.selected,s.core.confirmed?'研究者已确认':'候选',c.quote,e.id,src?.name||'',e.position,e.text,({pending:'待审核',confirmed:'已确认',rejected:'已搁置'})[c.status],src?.demo?'虚构演示资料':'用户导入',c.origin,c.rationale]);}
 return '﻿'+rows.map(r=>r.map(v=>'"'+String(v??'').replace(/^([=+@-])/,'​$1').replace(/"/g,'""')+'"').join(',')).join('\r\n');
}
export function addTextSource(s,{name,text,participant='未标注',role='研究资料'}){const pieces=splitText(text);if(!pieces.length)throw Error('资料内容为空，请填写文本。');const src={id:uid('S'),name,kind:'导入文本',participant,date:new Date().toLocaleDateString('sv-SE'),demo:false,included:true,role,status:'已解析'};s.sources.push(src);pieces.forEach((p,i)=>s.evidence.push({id:uid('E'),sourceId:src.id,position:'第 '+(i+1)+' 段',speaker:participant,text:p}));return src;}
