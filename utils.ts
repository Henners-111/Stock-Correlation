export function mean(a:number[]){ return a.reduce((s,v)=>s+v,0)/a.length }
export function cov(x:number[], y:number[]){
const mx = mean(x), my = mean(y);
let s = 0;
for(let i=0;i<x.length;i++) s += (x[i]-mx)*(y[i]-my);
return s/(x.length-1);
}
export function variance(a:number[]){ return cov(a,a) }
export function std(a:number[]){ return Math.sqrt(variance(a)) }
export function pearson(x:number[], y:number[]){ return cov(x,y)/(std(x)*std(y)) }


export function toLogReturns(prices:number[]){
const r: number[] = [];
for(let i=1;i<prices.length;i++) r.push(Math.log(prices[i]/prices[i-1]));
return r;
}


export function rolling(array:number[], window:number){
const out:number[] = [];
for(let i=0;i<=array.length-window;i++){
const slice = array.slice(i,i+window);
out.push(mean(slice));
}
return out;
}