const $ = id => document.getElementById(id);

function setStatus(msg) {
	const el = $('status');
	if (el) el.textContent = msg;
	// Also log for debugging
	console.log(msg);
}

// Choose API base depending on environment
// (replaced by override-enabled version below)
// Choose API base depending on environment
// - Localhost → local FastAPI
// - Otherwise → Render backend by default
// You can override via URL: ?api=https://your-backend.example.com
const urlApiOverride = new URLSearchParams(location.search).get('api');
const defaultApiBase = (location.hostname === 'localhost' || location.hostname === '127.0.0.1')
	? 'http://127.0.0.1:8000'
	: 'https://stock-correlation.onrender.com';
const API_BASE = urlApiOverride || defaultApiBase;

async function fetchStock(ticker, start, end) {
		const url = `${API_BASE}/history?ticker=${encodeURIComponent(ticker)}&start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`;
		const res = await fetch(url, { mode: 'cors' });
		if (!res.ok) throw new Error(`Backend error ${res.status}`);
		const json = await res.json();
		if (json && json.error) throw new Error(json.error);
		if (!json || !Array.isArray(json.data)) throw new Error('Malformed backend response');
		const cleaned = json.data.map(r => ({
				date: (typeof r.date === 'string') ? r.date.slice(0,10) : (new Date(r.date)).toISOString().slice(0,10),
				open: Number(r.open),
				high: Number(r.high),
				low: Number(r.low),
				close: Number(r.close),
				volume: r.volume != null ? Number(r.volume) : undefined,
		}))
		// Keep only valid rows with finite numbers and a date string
		.filter(r => r.date && Number.isFinite(r.open) && Number.isFinite(r.high) && Number.isFinite(r.low) && Number.isFinite(r.close));
		// Sort ascending by date just in case
		cleaned.sort((a,b)=> (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));
		// Deduplicate by date keeping the last
		const uniq = new Map();
		for (const row of cleaned) uniq.set(row.date, row);
		return Array.from(uniq.values());
}


function buildReturns(ts){
const closes = ts.map(x=>x.close);
const returns = [], dates = [];
for(let i=1;i<closes.length;i++){ returns.push(Math.log(closes[i]/closes[i-1])); dates.push(ts[i].date); }
return { returns, dates };
}
function alignByDates(tsA,tsB){
	const key = (d)=> String(d).slice(0,10);
	const mapB = new Map(tsB.map(x=>[key(x.date),x]));
	const a=[],b=[];
	for(const item of tsA){ const other=mapB.get(key(item.date)); if(other){ a.push(item); b.push(other); } }
	return { a,b };
}


function mean(a){ return a.reduce((s,v)=>s+v,0)/a.length; }
function cov(x,y){ const mx=mean(x), my=mean(y); let s=0; for(let i=0;i<x.length;i++) s+=(x[i]-mx)*(y[i]-my); return s/(x.length-1); }
function variance(a){ return cov(a,a); }
function pearson(x,y){ return cov(x,y)/(Math.sqrt(variance(x))*Math.sqrt(variance(y))); }
function fitOLS(x,y){ const b=cov(x,y)/variance(x); const a=mean(y)-b*mean(x); return { alpha:a, beta:b }; }
function cholesky2(C){ const a=Math.sqrt(C[0][0]); const b=C[0][1]/a; const c=Math.sqrt(C[1][1]-b*b); return [[a,0],[b,c]]; }
function gaussian(){
	// Box-Muller transform for standard normal
	let u=0,v=0; while(u===0) u=Math.random(); while(v===0) v=Math.random();
	return Math.sqrt(-2*Math.log(u))*Math.cos(2*Math.PI*v);
}
function multivariateNormalSamples(mu,Cov,n){
	const L=cholesky2(Cov);
	const out=[];
	for(let i=0;i<n;i++){
		const z0=gaussian();
		const z1=gaussian();
		out.push([
			mu[0]+L[0][0]*z0,
			mu[1]+L[1][0]*z0+L[1][1]*z1
		]);
	}
	return out;
}


async function run(){
try{
setStatus('Fetching data...');
const tickerA = $('tickerA').value;
const tickerB = $('tickerB').value;
// Normalize dates to YYYY-MM-DD even if the browser formats as DD/MM/YYYY
const toISO = (s)=>{
	if(!s) return s;
	// If already YYYY-MM-DD
	if(/^\d{4}-\d{2}-\d{2}$/.test(s)) return s;
	// Try DD/MM/YYYY or MM/DD/YYYY using Date parsing with day-first fallback
	const parts = s.split(/[\/-]/);
	if(parts.length===3){
		// Guess: if first part has 4 digits, it's year-first
		if(parts[0].length===4){ return `${parts[0].padStart(4,'0')}-${parts[1].padStart(2,'0')}-${parts[2].padStart(2,'0')}`; }
		// Try day-first then month-first by checking if month<=12
		const d1 = `${parts[2]}-${parts[1].padStart(2,'0')}-${parts[0].padStart(2,'0')}`; // DD/MM/YYYY -> YYYY-MM-DD
		const d2 = `${parts[2]}-${parts[0].padStart(2,'0')}-${parts[1].padStart(2,'0')}`; // MM/DD/YYYY -> YYYY-MM-DD
		const isValid = (x)=>!isNaN(new Date(x).getTime());
		return isValid(d1) ? d1 : (isValid(d2) ? d2 : s);
	}
	// Fallback to Date parsing
	const d = new Date(s);
	if(!isNaN(d.getTime())){
		const m = String(d.getMonth()+1).padStart(2,'0');
		const day = String(d.getDate()).padStart(2,'0');
		return `${d.getFullYear()}-${m}-${day}`;
	}
	return s;
};
const start = toISO($('start').value);
const end = toISO($('end').value);
const shock = parseFloat($('shock').value)/100;
const windowSize = Math.max(5, parseInt($('window').value||'30',10));


const tsA = await fetchStock(tickerA,start,end);
const tsB = await fetchStock(tickerB,start,end);

// Quick diagnostics
const datesA = new Set(tsA.map(d=>d.date));
const datesB = new Set(tsB.map(d=>d.date));
const overlapCount = [...datesA].filter(x=>datesB.has(x)).length;
setStatus(`Fetched ${tickerA}: ${tsA.length} | ${tickerB}: ${tsB.length} | overlap days: ${overlapCount}`);


const {a,b} = alignByDates(tsA,tsB);
if (a.length < 2 || b.length < 2) throw new Error(`Not enough overlapping data (overlap=${overlapCount})`);
const RA = buildReturns(a); const RB = buildReturns(b);
const rA = RA.returns; const rB = RB.returns;
if (rA.length < 2 || rB.length < 2) throw new Error('Not enough return points');


const corrRes = fitOLS(rA,rB); const pearsonR=pearson(rA,rB);
const muA = mean(rA), muB = mean(rB);
// Expected B under shock will be computed from conditional mean below
let expectedB = NaN;


// Summary tiles
$('s-overlap').textContent = String(overlapCount);
$('s-r').textContent = isFinite(pearsonR) ? pearsonR.toFixed(3) : 'NA';
$('s-beta').textContent = isFinite(corrRes.beta) ? corrRes.beta.toFixed(3) : 'NA';
$('s-alpha').textContent = isFinite(corrRes.alpha) ? corrRes.alpha.toExponential(2) : 'NA';
const volA = Math.sqrt(variance(rA)), volB = Math.sqrt(variance(rB));
$('s-vol').textContent = `${volA.toFixed(3)} / ${volB.toFixed(3)}`;
$('s-cov').textContent = cov(rA,rB).toExponential(2);
setStatus(`Computed stats. r=${$('s-r').textContent}, beta=${$('s-beta').textContent}, overlap=${overlapCount}`);


// Monte Carlo: B | (A = muA + shock) is Normal with:
// mean = muB + (CovAB/VarA) * (shock), var = VarB - CovAB^2/VarA
const varA_ = cov(rA,rA), varB_ = cov(rB,rB), covAB_ = cov(rA,rB);
const meanBCond = muB + (covAB_ / varA_) * (shock);
const varBCond = Math.max(1e-12, varB_ - (covAB_ * covAB_) / varA_);
const bSims = Array.from({length:5000}, () => meanBCond + Math.sqrt(varBCond) * gaussian());
// Quantiles
const quant = (arr,p)=>{ const s=[...arr].sort((x,y)=>x-y); const k=Math.floor((s.length-1)*p); return s[k]; };
const q05 = quant(bSims,0.05), q50 = quant(bSims,0.50), q95 = quant(bSims,0.95);
expectedB = meanBCond;
$('s-expB').textContent = isFinite(expectedB) ? expectedB.toExponential(2) : 'NA';
$('s-quant').textContent = `${q05.toExponential(2)} / ${q50.toExponential(2)} / ${q95.toExponential(2)}`;
$('s-samples').textContent = String(bSims.length);


// Price series
Plotly.newPlot('ts_prices',[
	{x:a.map(d=>d.date),y:a.map(d=>d.close),name:tickerA,mode:'lines',line:{width:2}},
	{x:b.map(d=>d.date),y:b.map(d=>d.close),name:tickerB,mode:'lines',line:{width:2}},
],{title:`Price Series (${tickerA} vs ${tickerB})`,plot_bgcolor:'#0c1424',paper_bgcolor:'#121a2b',font:{color:'#e6edf7'}});
// Scatter & OLS
const xMin=Math.min(...rA), xMax=Math.max(...rA);
Plotly.newPlot('scatter',[
	{x:rA,y:rB,mode:'markers',name:'Returns',marker:{size:5,opacity:0.7,color:'#4f83ff'}},
	{x:[xMin,xMax],y:[xMin*corrRes.beta+corrRes.alpha,xMax*corrRes.beta+corrRes.alpha],mode:'lines',name:'OLS Line',line:{color:'#00c853',width:2}},
],{title:'Scatter with OLS',plot_bgcolor:'#0c1424',paper_bgcolor:'#121a2b',font:{color:'#e6edf7'}});
// Rolling 30-day correlation
const roll=[]; const w=windowSize; for(let i=0;i<=rA.length-w;i++){ roll.push(pearson(rA.slice(i,i+w),rB.slice(i,i+w))); }
Plotly.newPlot('rolling',[{x:RA.dates.slice(w-1),y:roll,mode:'lines',line:{color:'#4f83ff'}}],{title:`Rolling ${w}-day correlation`,yaxis:{range:[-1,1]},plot_bgcolor:'#0c1424',paper_bgcolor:'#121a2b',font:{color:'#e6edf7'}});
// Monte Carlo
Plotly.newPlot('mc',[{x:bSims,type:'histogram',nbinsx:50,marker:{color:'#4f83ff'}}],{title:`Monte Carlo ${tickerB} | conditional on ${Math.round(shock*100)}% shock to ${tickerA}`,plot_bgcolor:'#0c1424',paper_bgcolor:'#121a2b',font:{color:'#e6edf7'}});


}catch(e){
	setStatus('Error: '+e.message);
	// Clear charts to reflect error state
	try { Plotly.purge('ts_prices'); Plotly.purge('scatter'); Plotly.purge('rolling'); Plotly.purge('mc'); } catch {}
}
}
$('run').addEventListener('click',run);