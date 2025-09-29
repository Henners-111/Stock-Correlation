export interface OHLCV {
date: string;
open: number;
high: number;
low: number;
close: number;
volume?: number;
}


export interface TimeSeries {
ticker: string;
items: OHLCV[];
}


export interface ReturnsSeries {
ticker: string;
dates: string[];
returns: number[];
}


export interface CorrelationResult {
pearson: number;
beta: number;
alpha: number;
cov: number;
varA: number;
varB: number;
}