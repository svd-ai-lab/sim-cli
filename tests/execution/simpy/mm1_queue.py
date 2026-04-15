"""SimPy E2E — M/M/1 queueing system steady-state.

Single-server queue, Poisson arrivals at rate λ, exponential service
at rate μ. Theory:
    average queue length in system L = ρ/(1-ρ),  ρ=λ/μ
    average waiting time in queue W_q = ρ/(μ-λ)

We pick λ=2, μ=3 (ρ=2/3) → L_theory = 2.0, W_q_theory = 0.667 s.
Run for 10000 time units; acceptance: L within ±15%, W_q within ±20%.
"""
import json
import random
import simpy


def main():
    random.seed(42)
    LAMBDA, MU, T_END = 2.0, 3.0, 10000.0

    waits = []
    n_in_system_samples = []
    last_t = [0.0]
    n_in_sys = [0]
    area = [0.0]

    env = simpy.Environment()
    server = simpy.Resource(env, capacity=1)

    def update_area(now):
        area[0] += n_in_sys[0] * (now - last_t[0])
        last_t[0] = now

    def customer(env, server):
        update_area(env.now); n_in_sys[0] += 1
        arrival = env.now
        with server.request() as req:
            yield req
            wait = env.now - arrival; waits.append(wait)
            yield env.timeout(random.expovariate(MU))
        update_area(env.now); n_in_sys[0] -= 1

    def gen(env):
        while True:
            yield env.timeout(random.expovariate(LAMBDA))
            env.process(customer(env, server))

    env.process(gen(env))
    env.run(until=T_END)
    update_area(T_END)

    L_obs = area[0] / T_END
    Wq_obs = sum(waits) / len(waits)
    rho = LAMBDA / MU
    L_th = rho / (1 - rho)
    Wq_th = rho / (MU - LAMBDA)

    print(json.dumps({
        "ok": abs(L_obs - L_th) / L_th < 0.15 and abs(Wq_obs - Wq_th) / Wq_th < 0.20,
        "L_observed": L_obs, "L_theory": L_th,
        "Wq_observed": Wq_obs, "Wq_theory": Wq_th,
        "n_customers": len(waits),
    }))


if __name__ == "__main__":
    main()
