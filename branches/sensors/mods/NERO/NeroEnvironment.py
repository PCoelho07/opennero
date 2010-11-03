import time
from math import *
from OpenNero import *
from NERO.module import *
from constants import *
from common.fitness import Fitness, FitnessStats
from copy import copy
from random import *

MAX_SPEED = 12
MAX_SD = 100
OBSTACLE = (1 << 0)
AGENT = (1 << 0)
FLAG_SENSORS = [(-180,-90), (-90,-60), (-60,-30), (-30,-15), (-15, 0), (-5, 5), (0, 15), (15, 30), (30, 60), (60, 90), (90, 180)]

class AgentState:
    """
    State that we keep for each agent
    """
    def __init__(self):
        self.id = -1
        # current x, y, heading pose
        self.pose = (0, 0, 0)
        # previous x, y, heading pose
        self.prev_pose = (0, 0, 0)
        # starting position
        self.initial_position = Vector3f(0, 0, 0)
        # starting orientation
        self.initial_rotation = Vector3f(0, 0, 0)        
        self.time = time.time()
        self.start_time = self.time
        self.total_damage = 0
        self.curr_damage = 0
        self.fitness = Fitness()
        self.prev_fitness = Fitness()
        self.final_fitness = 0
        self.animation = 'stand'

class NeroEnvironment(Environment):
    """
    Environment for the Nero
    """
    def __init__(self):
        from NERO.module import getMod
        """
        Create the environment
        """
        print "CREATING NERO ENVIRONMENT: " + str(dir(module))
        Environment.__init__(self) 
        
        self.curr_id = 0
        self.step_delay = 0.25 # time between steps in seconds
        self.max_steps = 20
        self.time = time.time()
        self.MAX_DIST = pow((pow(XDIM, 2) + pow(YDIM, 2)), .5)
        self.states = {}
        self.speedup = 0
        
        self.pop_state = {}
        
        abound = FeatureVectorInfo() # actions
        sbound = FeatureVectorInfo() # sensors
        rbound = FeatureVectorInfo() # rewards
        
        # actions
        abound.add_continuous(-1,1) # forward/backward speed
        abound.add_continuous(-0.2, 0.2) # left/right turn (in radians)
        
        # 5 x Wall Sensors
        sbound.add_continuous(0, 1) # -60 deg        
        sbound.add_continuous(0, 1) # -30 deg
        sbound.add_continuous(0, 1) # straight ahead
        sbound.add_continuous(0, 1) # 30 deg
        sbound.add_continuous(0, 1) # 60 deg
        
        # 5 x Foe Sensors
        #sbound.add_continuous(0, 1) # -60 deg        
        #sbound.add_continuous(0, 1) # -30 deg
        #sbound.add_continuous(0, 1) # straight ahead
        #sbound.add_continuous(0, 1) # 30 deg
        #sbound.add_continuous(0, 1) # 60 deg
        
        # 5 x Friend Sensors
        #sbound.add_continuous(0, 1) # -60 deg        
        #sbound.add_continuous(0, 1) # -30 deg
        #sbound.add_continuous(0, 1) # straight ahead
        #sbound.add_continuous(0, 1) # 30 deg
        #sbound.add_continuous(0, 1) # 60 deg
        
        # 11 x Flag Sensors
        for fs in FLAG_SENSORS:
            sbound.add_continuous(0,1)
        
        self.agent_info = AgentInitInfo(sbound, abound, rbound)
    
    def out_of_bounds(self, pos):
        """
        Checks if a given position is in bounds
        """
        return pos.x < 0 or pos.y < 0 or pos.x > XDIM or pos.y > YDIM
    
    def reset(self, agent):
        """
        reset the environment to its initial state
        """
        state = self.get_state(agent)
        agent.state.position = copy(state.initial_position)
        agent.state.rotation = copy(state.initial_rotation)
        state.pose = (state.initial_position.x, state.initial_position.y, state.initial_rotation.z)
        state.prev_pose = state.pose
        state.total_damage = 0
        state.curr_damage = 0
        state.prev_fitness = state.fitness
        state.fitness = Fitness()
        #update client fitness
        from client import set_stat
        ff = self.getFriendFoe(agent)
        return True
    
    def get_agent_info(self, agent):
        """
        return a blueprint for a new agent
        """
        # adding wall sensors
        #for angle in [-60, -30, 0, 30, 60]:
        #    ray_sensor = RaySensor(cos(radians(-60)),
        #                           sin(radians(-60)),
        #                           0,
        #                           MAX_SD,
        #                           OBSTACLE)
        #    print ray_sensor
        #    agent.add_sensor(ray_sensor)
        return self.agent_info
   
    def get_state(self, agent):
        """
        Returns the state of an agent
        """
        if agent in self.states:
            return self.states[agent]
        else:
            self.states[agent] = AgentState()
            self.states[agent].id = agent.state.id
            return self.states[agent]

    def getStateId(self, id):
        """
        Searches for the state with the given ID
        """
        for state in self.states:
            if id == self.states[state].id:
                return self.states[state]
        else:
            return - 1
            
    def getFriendFoe(self, agent):
        """
        Returns lists of all friend agents and all foe agents.
        """
        friend = []
        foe = []
        friend = self.states.values()
        foe = []
        return (friend, foe)

    def target(self, agent):
        #Get list of all targets
        ffr = self.getFriendFoe(agent)
        alt = ffr[1]#ffr[0] + ffr[1]
        if (ffr[0] == []):
            return None

        state = self.get_state(agent)
        
        #sort in order of variance from 0~2 degrees (maybe more)
        valids = []
        for curr in alt:
            fd = self.distance(state.pose,(curr.pose[0],curr.pose[1]))
            if fd != 0:
                fh  = ((degrees(atan2(curr.pose[1]-state.pose[1],curr.pose[0] - state.pose[0])) - state.pose[2]) % 360)
            else:
                fh = 0
            fh = abs(fh)
            if fh <= 2:
                valids.append((curr,fd,fh))
             
        #Valids contains (state,distance,heading to distance) pairs
        #get one that is nearest based on distance / cos(radians(degrees() * 20))
        top = None 
        top_v = 'A'

        for (curr,fd,fh) in valids:
            if top_v == 'A' or top_v > (fd / cos(radians(fh * 20))):
                top = curr
                top_v = (fd/cos(radians(fh * 20)))

        return top


    def step(self, agent, action):
        """
        2A step for an agent
        """
        from NERO.module import getMod, parseInput
        # check if the action is valid
        assert(self.agent_info.actions.validate(action))
        
        startScript('NERO/menu.py')
        data = script_server.read_data()
        while data:
            parseInput(data.strip())
            data = script_server.read_data()

        state = self.get_state(agent)

        #Initilize Agent state
        if agent.step == 0:
            p = agent.state.position
            agent.state.rotation.z = randrange(360)
            r = agent.state.rotation
            
            state.initial_position = p
            state.initial_rotation = r
            
            state.pose = (p.x, p.y, r.z)
            state.prev_pose = (p.x, p.y, r.z)
            self.pop_state[agent.org.id] = state

        #Spawn more agents if there are more to spawn (Staggered spawning times tend to yeild better behavior)
        if agent.step == 3:
            if getMod().getNumToAdd() > 0:
                dx = randrange(XDIM/20) - XDIM/40
                dy = randrange(XDIM/20) - XDIM/40
                getMod().addAgent((XDIM/2 + dx, YDIM/3 + dy, 2))

        # Update Damage totals
        state.total_damage += state.curr_damage
        damage = state.curr_damage
        state.curr_damage = 0
        
        #Add current unit to pop_state
        self.pop_state[agent.org.id] = state 
        
        #Fitness Function Parameters
        fitness = getMod().weights
        distance_st = getMod().dta
        distance_ae = getMod().dtb
        distance_af = getMod().dtc
        friendly_fire = getMod().ff

        # the position and the rotation of the agent on-screen
        position = agent.state.position
        rotation = agent.state.rotation
        
        # get the current pose of the agent
        (x, y, heading) = state.pose
        
        # get the actions of the agent
        move_by = action[0]
        turn_by = degrees(action[1])
        
        # figure out the new heading
        new_heading = wrap_degrees(heading, turn_by)
        
        # figure out the new x,y location
        new_x = x + MAX_SPEED * cos(radians(new_heading)) * move_by
        new_y = y + MAX_SPEED * sin(radians(new_heading)) * move_by
        
        # figure out the firing location
        fire_x = x + self.MAX_DIST * cos(radians(new_heading))
        fire_y = y + self.MAX_DIST * sin(radians(new_heading))
        
        # see if we can move forward
        new_position = copy(position)
        new_position.x, new_position.y = new_x, new_y
        distance_ahead = self.raySense(agent, turn_by, MAX_SPEED * move_by, OBSTACLE)
        safe = (distance_ahead >= 1)
        if not safe:
            # keep the position the same if we cannot move
            new_position = agent.state.position
        
        # draw the line of fire
        fire_pos = copy(position)
        fire_pos.x, fire_pos.y = fire_x, fire_y
        
        # calculate if we hit anyone
        data = self.target(agent)
        #string = agent.state.label + str(len(data)) + ": "
        hit = 0
        if data != None:#len(data) > 0:
            sim = data
            #string += str(sim.label) + "," + str(sim.id) + ";"
            target = self.getStateId(sim.id)
            if target != -1:
                target.curr_damage += 1 * friendly_fire
        
        # calculate friend/foe
        ffr = self.getFriendFoe(agent)
        if ffr[0] == []:
            return 0 #Corner Case
        ff = []
        ff.append(self.nearest(state.pose, state.id, ffr[0]))
        ff.append(self.nearest(state.pose, state.id, ffr[1]))
        
        st = 0
        ae = 0
        
        #calculate fitness
        sg = -action[0]
        if ff[0] != 1 and self.distance(ff[0].pose,state.pose) != 0:
            st = distance_st / self.distance(ff[0].pose,state.pose)
        if ff[1] != 1 and self.distance(ff[1].pose,state.pose) != 0:
            ae = distance_ae / self.distance(ff[1].pose,state.pose)
        af = (distance_af/self.flag_distance(agent))
        ht = hit
        vf = -damage        
        
        #update current state data with fitness values
        state.fitness[Fitness.STAND_GROUND] += sg
        state.fitness[Fitness.STICK_TOGETHER] += st
        state.fitness[Fitness.APPROACH_ENEMY] += ae
        state.fitness[Fitness.APPROACH_FLAG] += af
        state.fitness[Fitness.HIT_TARGET] += ht
        state.fitness[Fitness.AVOID_FIRE] += vf
        
        # make the calculated motion
        position.x, position.y = state.pose[0], state.pose[1]
        agent.state.position = position
        rotation.z = new_heading
        agent.state.rotation = rotation
        state.prev_pose = state.pose
        state.pose = (new_position.x, new_position.y, rotation.z)
        state.time = time.time()
        
        #If it's the final state, handle clean up behaviors
        #You may get better behavior if you move this to epsiode_over
        if agent.step >= self.max_steps - 1:
            rtneat = agent.get_rtneat()
            pop = rtneat.get_population_ids()
            if len(pop) == 0:
                return 0
            avg,sig = self.generate_averages(agent)
            sums = Fitness()
            sums = getMod().weights * (state.fitness - avg) / sig
            #Add current unit to pop_state
            self.pop_state[agent.org.id] = state
            state.final_fitness = sums.sum()
            print 'FITNESS:',getMod().weights * state.fitness,'=> Z-SCORE:', state.final_fitness
            return state.final_fitness

        return 0
    
    def raySense(self, agent, heading_mod, dist, types=0, draw=True, foundColor = Color(255, 0, 128, 128), noneColor = Color(255, 0, 255, 255) ):
        """
        Sends out a ray to find objects via line of sight, using irrlicht.
        """
        state = self.get_state(agent)
        firing = agent.state.position
        rotation = agent.state.rotation
        heading = radians(rotation.z + heading_mod)
        firing.x += dist * cos(heading)
        firing.y += dist * sin(heading)
        p0 = agent.state.position
        p1 = firing
        result = getSimContext().findInRay(p0, p1, types, draw, foundColor, noneColor)
        if len(result) > 0:
            (sim, hit) = result
            ray = p1 - p0
            len_ray = ray.getLength()
            data = hit - p0
            len_data = data.getLength()
            if len_ray != 0:
                return len_data / len_ray
        return 1

    def sense(self, agent):
        """ 
        figure out what the agent should sense 
        """
        state = self.get_state(agent)
        observations = self.agent_info.sensors.get_instance()
        vx = []
        
        state = self.get_state(agent)
        vx.append(self.raySense(agent, -60, MAX_SD, OBSTACLE))
        vx.append(self.raySense(agent, -30, MAX_SD, OBSTACLE))
        vx.append(self.raySense(agent, 0, MAX_SD, OBSTACLE))
        vx.append(self.raySense(agent, 30, MAX_SD, OBSTACLE))
        vx.append(self.raySense(agent, 60, MAX_SD, OBSTACLE))
        
        flag_loc = self.flag_loc()
        fx, fy = flag_loc.x, flag_loc.y
        (x, y, h) = state.pose
        fd = hypot(fx - x, fy - y)
        fh = 0
        if fd != 0:
            atan2
        if fd != 0:
            fh = degrees(atan2(fy-y,fx-x)) - h
        else:
            fh = 0
        while fh < 180:
            fh += 360
        while fh > 180:
            fh -= 360
        for (th1, th2) in FLAG_SENSORS:
            if fh > th1 and fh <= th2:
                vx.append(min(1.0, max(0, (self.MAX_DIST - fd)/self.MAX_DIST)))
            else:
                vx.append(0)
        for iter in range(len(vx)):
            observations[iter] = vx[iter]
        return observations
   
    def flag_loc(self):
        """
        Returns the current location of the flag
        """
        from NERO.module import getMod
        return getMod().flag_loc

    def flag_distance(self, agent):
        """
        Returns the distance of the current agent from the flag
        """
        pos = self.get_state(agent).pose
        return pow(pow(float(pos[0]) - self.flag_loc().x, 2) + pow(float(pos[1]) - self.flag_loc().y, 2), .5)

    def distance(self, agloc, tgloc):
        """
        Returns the distance between agloc and tgloc
        """
        return pow(pow(float(agloc[0] - tgloc[0]), 2) + pow(float(agloc[1] - tgloc[1]), 2), .5)

    def angle(self, agloc, tgloc):
        """
        returns the angle between agloc and tgloc (test before using to make sure it's returning what you think it is)
        """
        if(agloc[1] == tgloc[1]):
            return 0
        (x, y, heading) = agloc
        (xt, yt, ignore) = tgloc
        # angle to target
        theading = atan2(yt - y, xt - x)
        rel_angle_to_target = theading - radians(heading)
        return rel_angle_to_target

    def nearest(self, cloc, id, array):
        """
        Returns the nearest agent in array to agent with id id at current location.
        """
        # TODO: this needs to only be computed once per tick, not per agent
        nearest = 1
        value = self.MAX_DIST * 5
        for other in array:
            if id == other.id:
                continue
            if self.distance(cloc, other.pose) < value:
                nearest = other
                value - self.distance(cloc, other.pose)
        return nearest

    def set_animation(self, agent, state, animation):
        """
        Sets current animation
        """
        if state.animation != animation:
            agent.state.setAnimation(animation)
            state.animation = animation
    
    def is_active(self, agent):
        """ return true when the agent should act """
        state = self.get_state(agent)
        # interpolate between prev_pose and pose
        (x1, y1, h1) = state.prev_pose
        (x2, y2, h2) = state.pose
        if x1 != x2 or y1 != y2:
            fraction = 1.0
            if self.get_delay() != 0:
                fraction = min(1.0, float(time.time() - state.time) / self.get_delay())
            pos = agent.state.position
            pos.x = x1 * (1 - fraction) + x2 * fraction
            pos.y = y1 * (1 - fraction) + y2 * fraction
            agent.state.position = pos
            self.set_animation(agent, state, 'run')
        else:
            self.set_animation(agent, state, 'stand')
        if time.time() - state.time > self.get_delay():
            state.time = time.time()
            return True
        else:
            return False
    
    def is_episode_over(self, agent):
        """
        is the current episode over for the agent?
        """
        from NERO.module import getMod
        self.max_steps = getMod().lt
        state = self.get_state(agent)
        if self.max_steps != 0 and agent.step >= self.max_steps:
            return True
        if getMod().hp != 0 and state.total_damage >= getMod().hp:
            return True
        else:
            return False
    
    def cleanup(self):
        """
        cleanup the world
        """
        killScript('NERO/menu.py')
        return True

    def generate_averages(self,agent):
        """
        Generates averages for using Z-Fitness
        """
        rtneat = agent.get_rtneat()
        pop = rtneat.get_population_ids()
        # calculate population average
        # calculate population standard deviation
        stats = FitnessStats()
        for x in pop:
            f = self.pop_state[x].prev_fitness
            stats.add(f)
        stats.add(self.pop_state[agent.org.id].prev_fitness)
        return stats.mean, stats.stddev()
    
    def clear_averages(self):
        for x in self.pop_state:
            self.pop_state[x].prev_fitness = Fitness()

    def get_delay(self):
        """
        Set simulation delay
        """
        return self.step_delay * (1.0 - self.speedup)
