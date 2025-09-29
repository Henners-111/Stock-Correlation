import { pearson, cov, variance, mean } from './utils.js';


export function fitOLS(x:number[], y:number[]){
const b = cov(x,y)/variance(x);
const a = mean(y) - b*mean(x);
return { alpha: a, beta: b };
}


export function correlationResult(rA:number[], rB:number[]){
if(rA.length !== rB.length) throw new Error('length mismatch');
return {
pearson: pearson(rA,rB),
cov: cov(rA,rB),
varA: variance(rA),
varB: variance(rB),
...fitOLS(rA,rB)
};
}


// simple 2D Cholesky for positive-definite 2x2 cov matrix
export function cholesky2(C:number[][]){
const a = Math.sqrt(C[0][0]);
const b = C[0][1]/a;
const c = Math.sqrt(C[1][1]-b*b);
return [[a,0],[b,c]];
}


export function multivariateNormalSamples(mu:number[], Cov:number[][], n:number){
const L = cholesky2(Cov);
const out:number[][] = [];
for(let i=0;i<n;i++){
const z0 = gaussian();
const z1 = gaussian();
const x0 = mu[0] + L[0][0]*z0;
const x1 = mu[1] + L[1][0]*z0 + L[1][1]*z1;
out.push([x0,x1]);
}
return out;
}


function gaussian(){
// Box-Muller
let u=0,v=0; while(u===0) u=Math.random(); while(v===0) v=Math.random();
return Math.sqrt(-2*Math.log(u))*Math.cos(2*Math.PI*v);
}