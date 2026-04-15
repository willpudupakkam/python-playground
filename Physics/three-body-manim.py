from manim import *
import numpy as np

class ThreeBodyProblem(Scene):
    def construct(self):
        # Simulation parameters
        G = 1.0                 # gravitational constant
        dt = 0.01               # time step (in seconds of simulation per frame)
        sim_time = 20           # total simulation time (seconds)
        
        # Create three bodies with initial conditions
        # Each body is a Dot with custom attributes: r (position), v (velocity), mass
        bodies = []
        init_conditions = [
            # (pos, vel)
            (np.array([-1.0,  0.0, 0.]), np.array([ 0.0,  0.4, 0.])),
            (np.array([ 1.0,  0.0, 0.]), np.array([ 0.0, -0.4, 0.])),
            (np.array([ 0.0,  1.5, 0.]), np.array([ 0.4,  0.0, 0.])),
        ]
        colors = [RED, GREEN, BLUE]
        mass = 1.0
        
        for (pos, vel), color in zip(init_conditions, colors):
            dot = Dot(point=pos, color=color, radius=0.08)
            dot.r = pos.copy()
            dot.v = vel.copy()
            dot.mass = mass
            bodies.append(dot)
            self.add(dot)
        
        # Add traced paths for each body
        for body in bodies:
            path = TracedPath(body.get_center, stroke_width=2, stroke_color=body.get_color())
            self.add(path)
        
        # Define updater function
        def make_updater(body):
            def update(body_mob, dt_mob):
                # Compute net acceleration on this body
                a = np.zeros(3)
                for other in bodies:
                    if other is body:
                        continue
                    r_vec = other.r - body.r
                    dist = np.linalg.norm(r_vec)
                    # avoid singularity
                    if dist < 0.05:
                        continue
                    a += G * other.mass * r_vec / dist**3
                # Euler integration
                body.mob_v = body.v + a * dt
                body.mob_r = body.r + body.mob_v * dt
                # Update stored state
                body.v = body.mob_v
                body.r = body.mob_r
                # Move the dot
                body_mob.move_to(body.r)
            return update
        
        # Attach the updater to each body
        for body in bodies:
            body.add_updater(make_updater(body))
        
        # Run the simulation
        # During the wait, each body's updater is called every frame
        self.wait(sim_time)
        
        # Clean up updaters
        for body in bodies:
            body.clear_updaters()