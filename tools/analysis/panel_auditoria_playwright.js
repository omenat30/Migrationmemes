const {chromium}=require("/opt/node-tools/node_modules/playwright");
const fs=require("fs"),S=process.argv[2];
(async()=>{
  const b=await chromium.launch({executablePath:"/opt/pw-browsers/chromium"});
  const errs=[];
  const docs=fs.readdirSync(S+"/dbfull2").map(f=>JSON.parse(fs.readFileSync(S+"/dbfull2/"+f)));
  for (const [w,name] of [[1300,"d"],[400,"m"]]){
    const pg=await b.newPage({viewport:{width:w,height:900}});
    pg.on("pageerror",e=>errs.push(String(e)));
    pg.on("console",m=>{if(m.type()==="error")errs.push(m.text())});
    await pg.goto("file:///home/user/memecoin-migration-radar/dashboard/copy.html");
    await pg.waitForTimeout(500);
    await pg.evaluate(d=>{connected=true;wallets=d;meta={ts:Date.now()/1000-3600,sol_usd:104.2,analyzed:57,changes:[],cfg:{ver:"abc123"}};render()},docs);
    const r1=await pg.evaluate(()=>wallets.map(evalWallet).filter(e=>e.ok).map(e=>e.w.addr.slice(0,8)));
    await pg.click('#audit'); await pg.waitForTimeout(200);
    const r2=await pg.evaluate(()=>({st:state.audit,ok:wallets.map(evalWallet).filter(e=>e.ok).map(e=>[e.w.addr.slice(0,8),e.w.aud.rs]),fail:wallets.map(evalWallet).filter(e=>!e.ok&&e.w.status==="active").map(e=>[e.w.addr.slice(0,8),e.why.filter(x=>/audit|R encog|percentil|10 %|beneficio|bolsas|parcial/.test(x)).slice(0,2)])}));
    const fw=await pg.evaluate(()=>({vis:!document.getElementById("fwdcard").hidden,rows:document.querySelectorAll("#tblfwd tbody tr").length,sum:document.getElementById("fwdsum").textContent.slice(0,260)}));
    const ov=await pg.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth);
    console.log(name,"defecto:",r1.join(","));
    console.log(name,"auditoría:",JSON.stringify(r2.ok));
    if(name==="d"){console.log("activas que fallan en auditoría:",JSON.stringify(r2.fail).slice(0,900)); console.log("hacia adelante:",JSON.stringify(fw)); }
    console.log("overflowX",ov);
    await pg.screenshot({path:S+"/copy3_"+name+".png",fullPage:false});
  }
  console.log("errores:",JSON.stringify(errs));
  await b.close();
})();
