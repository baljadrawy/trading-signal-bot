"""P2-F0 v3 decision package: deterministic calculations (stdlib only, no Monte Carlo, no data read).

Run: python3 docs/p2/p2f0_v3_decision_calc.py   (prints every number quoted in P2F0_V3_DECISION_PACKAGE.md)
"""
import math
from statistics import NormalDist
N=NormalDist(); z=1.959963984540054
def wilson(k,n):
    p=k/n; d=1+z*z/n; c=(p+z*z/(2*n))/d; h=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/d
    return max(0,c-h), min(1,c+h)
def binom_cdf(k,n,p):
    return sum(math.comb(n,i)*p**i*(1-p)**(n-i) for i in range(k+1))
def kmax(n,bound):  # max events with Wilson UB <= bound
    k=-1
    while k+1<=n and wilson(k+1,n)[1]<=bound: k+=1
    return k
print("== C4: Wilson UB <= 0.05 ==")
for k in range(0,6):
    n=max(1,k)
    while wilson(k,n)[1]>0.05: n+=1
    print(f"k={k}: min n={n}")
print("P(pass UB<=0.05) by n and true PROVISIONAL rate p:")
for n in (50,73,100,150,200,300,500,1000):
    km=kmax(n,0.05)
    print(n, "kmax",km, {p: round(binom_cdf(km,n,p),3) if km>=0 else 0 for p in (0.0,0.005,0.01,0.02,0.03)})
print("screen-pass point<=0.10 at n, P(pass) at true 0.02/0.05/0.08:")
for n in (50,150,300):
    km=math.floor(0.10*n); print(n,{p:round(binom_cdf(km,n,p),3) for p in (0.02,0.05,0.08)})
print("== C7: Wilson UB <= 0.15 ==")
for k in range(0,5):
    n=max(1,k)
    while wilson(k,n)[1]>0.15: n+=1
    print(f"k={k}: min n={n}")
for n in (30,60,100,150):
    km=kmax(n,0.15); print(n,"kmax",km,{p:round(binom_cdf(km,n,p),3) for p in (0.0,0.02,0.033,0.05)})
print("fee-blind 1/30 vs base null screen rate: P(>=1 of 30)", {p: round(1-(1-p)**30,3) for p in (0.01,0.02)})
print("routing >=80%: P(point>=0.8 | true r), n=30/100")
for r in (0.6,0.65,0.7,0.8,0.9):
    print(r,[round(1-binom_cdf(math.ceil(0.8*n)-1,n,r),3) for n in (30,100,300)])
print("routing: n for Wilson half-width <= 0.05 at r=0.65:", next(n for n in range(10,2000) if (wilson(round(0.65*n),n)[1]-wilson(round(0.65*n),n)[0])/2<=0.05))
print("== Forward power, annualized alpha Sharpe S, 1 obs/day, one-sided 5% ==")
def power(S,n,alpha=0.05,deff=1.0):
    return 1-N.cdf(N.inv_cdf(1-alpha)-S*math.sqrt(n/365/deff))
def ndays(S,alpha=0.05,pw=0.8,deff=1.0):
    return math.ceil(((N.inv_cdf(1-alpha)+N.inv_cdf(pw))*math.sqrt(365)/S)**2*deff)
for S in (2,3,4,6):
    print(f"S={S}: days80 m=1 deff1 {ndays(S)}, deff1.25 {ndays(S,deff=1.25)}, Holm m=3 (a=0.05/3) {ndays(S,alpha=0.05/3)}")
print("power table m=1 deff=1:")
for n in (28,56,90,120,180,252,365,564):
    print(n,[round(power(S,n),2) for S in (2,3,4,6)], "MDE80 S=",round((N.inv_cdf(0.95)+N.inv_cdf(0.8))*math.sqrt(365/n),2),"SE(S)=",round(math.sqrt(365/n),2))
print("power m=3 Holm-first (a=.0167), deff 1.25 at 120/252/365:")
for n in (120,252,365):
    print(n,[round(power(S,n,alpha=0.05/3,deff=1.25),2) for S in (2,3,4)])
# winners curse: if in-sample alpha Sharpe estimate is S_hat from 13 days, haircut 0.5
print("v2 sizing: in-sample S_hat needed for n<=120 (haircut .5, deff 1):", round(2*(2.486*math.sqrt(365/120)),2))
print("SE of 13-day annualized Sharpe:", round(math.sqrt(365/13),2))
# CPU cost
cpu=2635; reps=100+100+50+300+270+420
print("battery reps",reps,"CPU-s/rep upper",round(cpu/reps,2))
