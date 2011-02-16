#include "core/Common.h"
#include "game/SimEntity.h"
#include "game/SimContext.h"
#include "game/Kernel.h"
#include "ai/AIObject.h"
#include "ai/AgentBrain.h"
#include "ai/rtneat/rtNEAT.h"
#include "rtneat/population.h"
#include "rtneat/network.h"
#include "scripting/scriptIncludes.h"
#include "math/Random.h"
#include <ostream>
#include <fstream>

namespace OpenNero
{
 
    /// @cond
    BOOST_SHARED_DECL(SimEntity);
    /// @endcond

    using namespace NEAT;

    namespace {
        const size_t kNumSpeciesTarget = 5; ///< target number of species in the population
        const double kCompatMod = 0.1; ///< compatibility threshold modifier
        const double kMinCompatThreshold = 0.3; // minimum species compatibility threshold

        /// compare two organisms by fitness
        bool fitness_less(OrganismPtr a, OrganismPtr b)
        {
            return a->fitness < b->fitness;
        }
    }

    /// Constructor
    /// @param filename name of the file with the initial population genomes
    /// @param param_file file with RTNEAT parameters to load
    /// @param population_size size of the population to construct
    RTNEAT::RTNEAT(const std::string& filename, const std::string& param_file, size_t population_size)
        : mPopulation()
        , mWaitingBrainList()
		, mBrainList()
        , mOffspringCount(0)
    {
        NEAT::load_neat_params(Kernel::findResource(param_file));
        NEAT::pop_size = population_size;
        NEAT::time_alive_minimum = 1; // organisms cannot be removed before the are evaluated at least once
        mPopulation.reset(new Population(filename, population_size));
        AssertMsg(mPopulation, "initial population creation failed");
        mOffspringCount = mPopulation->organisms.size();
        AssertMsg(mOffspringCount == population_size, "population has " << mOffspringCount << " organisms instead of " << population_size);
        for (size_t i = 0; i < mPopulation->organisms.size(); ++i)
        {
			PyOrganismPtr brain(new PyOrganism(mPopulation->organisms[i]));
            mWaitingBrainList.push(brain);
        }
    }

    /// Constructor
    /// @param param_file RTNEAT parameter file
    /// @param inputs number of inputs
    /// @param outputs number of outputs
    /// @param population_size size of the population to construct
    /// @param noise variance of the Gaussian used to assign initial weights
    RTNEAT::RTNEAT(const std::string& param_file, size_t inputs, size_t outputs, size_t population_size, F32 noise)
        : mPopulation()
        , mWaitingBrainList()
		, mBrainList()
        , mOffspringCount(0)
    {
        NEAT::load_neat_params(Kernel::findResource(param_file));
        NEAT::pop_size = population_size;
        NEAT::time_alive_minimum = 1; // organisms cannot be removed before the are evaluated at least once
        GenomePtr genome(new Genome(inputs, outputs, 0, 0));
        mPopulation.reset(new Population(genome, population_size, noise));
        AssertMsg(mPopulation, "initial population creation failed");
        mOffspringCount = mPopulation->organisms.size();
        AssertMsg(mOffspringCount == population_size, "population has " << mOffspringCount << " organisms instead of " << population_size);
        for (size_t i = 0; i < mPopulation->organisms.size(); ++i)
        {
			PyOrganismPtr brain(new PyOrganism(mPopulation->organisms[i]));
            mWaitingBrainList.push(brain);
        }
    }
    
    /// Destructor
    RTNEAT::~RTNEAT()
    {

    }
    
    /// are we ready to spawn a new organism?
    bool RTNEAT::ready() 
    {
        return !mWaitingBrainList.empty();
    }
    
    /// have we been deleted?
    bool RTNEAT::have_organism(AgentBrainPtr agent)
    {
        BrainBodyMap::left_map::const_iterator found;
        found = mBrainBodyMap.left.find(agent->GetBody());
        return (found != mBrainBodyMap.left.end());
    }
    
    /// get the organism currently assigned to the agent
    PyOrganismPtr RTNEAT::get_organism(AgentBrainPtr agent)
    {
        BrainBodyMap::left_map::const_iterator found;
        found = mBrainBodyMap.left.find(agent->GetBody());
        if (found != mBrainBodyMap.left.end())
        {
            return found->second;
        }
        else
        {
            PyOrganismPtr brain = mWaitingBrainList.front();
            mWaitingBrainList.pop();
            mBrainBodyMap.insert(BrainBodyMap::value_type(agent->GetBody(), brain));
            return brain;
        }

    }
    
    /// release the organism that was being used by the agent
    void RTNEAT::release_organism(AgentBrainPtr agent)
    {
        BrainBodyMap::left_map::const_iterator found;
        found = mBrainBodyMap.left.find(agent->GetBody());
        Assert(found != mBrainBodyMap.left.end());
        mWaitingBrainList.push(found->second);
    }

    /// save a population to a file
    bool RTNEAT::save_population(const std::string& pop_file)
    {
        std::string fname = Kernel::findResource(pop_file, false);
        std::ofstream output(fname.c_str());
        if (!output) {
            LOG_ERROR("Could not open file " << fname);
            return false;
        }
        else
        {
            LOG_F_DEBUG("ai.rtneat", "Saving population to " << fname);
            //output << mPopulation;
            mPopulation->print_to_file(output);
            output.close();
            return true;
        }
    }
    
    void RTNEAT::deleteUnit(PyOrganismPtr brain)
    {
        // Push the brain onto the back of the waiting brain queue
        mWaitingBrainList.push(brain);

        // disconnect brain from body
        mBrainBodyMap.right.erase(brain);

        // Increment the deletion counter
        ++mTotalUnitsDeleted;
    }
    
    void RTNEAT::ProcessTick( float32_t incAmt )
    {
		// Increment the spawn tick and evolution tick counters
		++mSpawnTickCount;
		++mEvolutionTickCount;

        // iterate through the body id's and check to see if they have died
        // if they have, we need to remove them from the books and put their
        // brains back into the evaluation queue
        BrainBodyMap::left_map::const_iterator iter = mBrainBodyMap.left.begin();
        BrainBodyMap::left_map::const_iterator iend = mBrainBodyMap.left.end();
        while (iter != iend)
        {
            AIObjectPtr body = iter->first;
            PyOrganismPtr brain = iter->second;
            SimEntityPtr found = Kernel::instance().GetSimContext()->getSimulation()->Find(body->GetId());
            ++iter; // iterate first, deleteUnit may invalidate our pointer by changing BBM!
            if (!found) {
                deleteUnit(brain);
            }
        }

        // Evaluate all brains' scores
        evaluateAll();

        // If the total number of units spawned so far exceeds the threshold value AND enough
        // ticks have passed since the last evolution, then a new evolution may commence.
        if (mTotalUnitsDeleted >= mUnitsToDeleteBeforeFirstJudgment  &&  mEvolutionTickCount >= mTimeBetweenEvolutions) {
            //Judgment day!
            evolveAll();
            mEvolutionTickCount = 0;
        }
	}
    
    void RTNEAT::evaluateAll()
    {
        // calculate Z-score for all the organisms we know about
        // 1. Let d be the number of dimensions in the fitness function
        // 2. Let w be the vector of d weights of relative importance (user-assigned)
        
        // 3. Let fitness_mean be the vector of d means of each dimension of the fitness function
        Reward fitness_mean;
        // 4. Let fitness_stdev be the vector of d standard deviations for each dimension of the fitness
        Reward fitness_stdev;
        
        for (vector<PyOrganismPtr>::iterator iter = mBrainList.begin(); iter != mBrainList.end(); ++iter) {
            if ((*iter)->GetOrganism()->time_alive >= NEAT::time_alive_minimum) {
                if ( !((*iter)->GetOrganism()->time_alive % NEAT::time_alive_minimum) && 
                     (*iter)->GetOrganism()->time_alive > 0 )
                {
                    (*iter)->GetOrganism()->time_alive++;
                    AssertMsg(false, "FIXME/TODO: start next trial to normalize by time_alive_minimum");
                }
                AssertMsg(false, "FIXME/TODO: add stats samples");
            }
        }

        //mScoreHelper->doCalculations();
        AssertMsg(false, "FIXME/TODO: mScoreHelper->doCalculations()");

        F32 minAbsoluteScore = 0; // min of 0, min abs score
        F32 maxAbsoluteScore = -FLT_MAX; // max raw score
        PyOrganismPtr champ; // brain with best raw score

        for (vector<PyOrganismPtr>::iterator iter = mBrainList.begin(); iter != mBrainList.end(); ++iter) {
            if ((*iter)->GetOrganism()->time_alive >= NEAT::time_alive_minimum) {
                AssertMsg(false, "FIXME/TODO: calculate mAbsoluteScore");

                if ((*iter)->mAbsoluteScore < minAbsoluteScore)
                    minAbsoluteScore = (*iter)->mAbsoluteScore;
				if ((*iter)->mAbsoluteScore > maxAbsoluteScore)
					maxAbsoluteScore = (*iter)->mAbsoluteScore;
            }
        }

        if (minAbsoluteScore < 0) {
            for (vector<PyOrganismPtr>::iterator iter = mBrainList.begin(); iter != mBrainList.end(); ++iter) {
                if ((*iter)->GetOrganism()->time_alive >= NEAT::time_alive_minimum) {
                    F32 modifiedFitness = (*iter)->mAbsoluteScore - minAbsoluteScore;
                    if (modifiedFitness < 0)
                        modifiedFitness = 0;


                    if (!((*iter)->GetOrganism()->smited)) 
					{
                        (*iter)->GetOrganism()->fitness = modifiedFitness;
					}
                    else 
                    { 
                        (*iter)->GetOrganism()->fitness = 0.01 * modifiedFitness;
                    }
                }
            }
        }
        else
        {
            for (vector<PyOrganismPtr>::iterator iter = mBrainList.begin(); iter != mBrainList.end(); ++iter) {
                if ((*iter)->GetOrganism()->time_alive >= NEAT::time_alive_minimum) {

                    if (!((*iter)->GetOrganism()->smited)) 
                        (*iter)->GetOrganism()->fitness = (*iter)->mAbsoluteScore;
                    else 
                    { 
                        (*iter)->GetOrganism()->fitness = 0.01 * (*iter)->mAbsoluteScore;
                    }
                }
            }
        }
    }
    
    void RTNEAT::evolveAll()
    {
        // Remove the worst organism
        OrganismPtr deadorg = mPopulation->remove_worst();

        //We can try to keep the number of species constant at this number
        U32 num_species_target=4;
        U32 compat_adjust_frequency = mBrainList.size()/10;
        if (compat_adjust_frequency < 1)
            compat_adjust_frequency = 1;

        SpeciesPtr new_species;

        // Sometimes, if all organisms are beneath the minimum "time alive" threshold, no organism will be removed
        // If an organism *was* actually removed, then we can proceed with replacing it via the evolutionary process
        if (deadorg) {
            NEAT::OrganismPtr new_org;

            // Estimate all species' fitnesses
            for (vector<SpeciesPtr>::iterator curspec = (mPopulation->species).begin(); curspec != (mPopulation->species).end(); ++curspec) {
                (*curspec)->estimate_average();

                // Calculate an average based upon the actual scores (not the adjusted, non-negative scores that are
                // being passed to organisms' fitness fields) so that we can display an average that makes sense from
                // evaluation to evaluation
                F32 scoreavg = 0;
                S32 samplesize = 0;
                vector<OrganismPtr>::iterator curorg = mPopulation->organisms.begin();
                for ( ; curorg != mPopulation->organisms.end(); ++curorg) {
                    SpeciesPtr species = (*curorg)->species.lock();                    
                    if (species == (*curspec)) {
                        vector<PyOrganismPtr>::iterator curbrain = mBrainList.begin();
                        for ( ; curbrain != mBrainList.end(); ++curbrain) {
                            if ( (*curbrain)->GetOrganism() == (*curorg) && 
                                 (*curbrain)->GetOrganism()->time_alive >= NEAT::time_alive_minimum) {
                                scoreavg += (*curbrain)->mAbsoluteScore;
                                ++samplesize;                            
                            }
                        }
                    }
                }
                if (samplesize > 0)
                    scoreavg /= (F32)samplesize;

                LOG_F_DEBUG("ai.rtneat", "Species " << (*curspec)->id << 
                            " size: " << (*curspec)->organisms.size() << 
                            " elig. size: " << samplesize <<
                            " avg. score: " << scoreavg);
            }

            // Print out info about the organism that was killed off
            for (vector<PyOrganismPtr>::iterator iter = mBrainList.begin(); iter != mBrainList.end(); ++iter) {
                if ((*iter)->GetOrganism() == deadorg) {
                    LOG_F_DEBUG("ai.rtneat", "Org to kill: score = " << (*iter)->mAbsoluteScore);
                    break;
                }
            }

            // TODO: currently assuming this was not used
            //m_Population->memory_pool->isEmpty();
            //if(Platform::getRandom()<=s_MilestoneProbability && !m_Population->memory_pool->isEmpty())// && meets probability requirement)
            //{
            //    // Reproduce an organism with the same traits as the "memory pool".
            //    new_org.reset(mPopulation->memory_pool)->reproduce_one(mOffspringCount, mPopulation, mPopulation->species);
            //}
            //else
            //{
            // Reproduce a single new organism to replace the one killed off.
            new_org = (mPopulation->choose_parent_species())->reproduce_one(mOffspringCount, mPopulation, mPopulation->species, 0,0);
            //}
            ++mOffspringCount;

            //Every compat_adjust_frequency reproductions, reassign the population to new species
            if (mOffspringCount % compat_adjust_frequency == 0) {

                U32 num_species = mPopulation->species.size();
                F64 compat_mod=0.1;  //Modify compat thresh to control speciation

                // This tinkers with the compatibility threshold, which normally would be held constant
                if (num_species < num_species_target)
                    NEAT::compat_threshold -= compat_mod;
                else if (num_species > num_species_target)
                    NEAT::compat_threshold += compat_mod;

                if (NEAT::compat_threshold < 0.3) 
                    NEAT::compat_threshold = 0.3;

                //Go through entire population, reassigning organisms to new species
                vector<OrganismPtr>::iterator curorg = mPopulation->organisms.begin();
                vector<OrganismPtr>::iterator orgend = mPopulation->organisms.end();
                for (; curorg != orgend; ++curorg) {
                    mPopulation->reassign_species(*curorg);
                }
            }

            // Iterate through all of the Brains
            //   - find the one whose Organism was killed off
            //   - link that Brain to the newly created Organism, effectively 
            //     doing a "hot swap" of the Organisms in that Brain.
            for (vector<PyOrganismPtr>::iterator iter = mBrainList.begin(); iter != mBrainList.end(); ++iter) {
                if ((*iter)->GetOrganism() == deadorg) {
                    PyOrganismPtr brain = *iter;
                    brain->SetOrganism(new_org);
                    AssertMsg(false, "FIXME/TODO: (*iter)->m_Stats.resetAll();");
                    deleteUnit(brain);
                    break;
                }
            }
        }
    }
    
    U32 Stats::s_RunningAverageSampleSize = 2;

    /// Number of trials processed over the unit's lifetime
    Stats::Stats(const RewardInfo& info) 
        : m_NumLifetimeTrials(0)
        , m_ZeroStats(info.getInstance())
        , m_Stats(m_ZeroStats)
        , m_LifetimeAverage(m_ZeroStats)
    {
    
    }
            
    /// Reset all stats
    void Stats::resetAll()
    {
    
    }
    
    /// start next trial
    void Stats::startNextTrial()
    {
        ++m_NumLifetimeTrials;
        if (m_NumLifetimeTrials <= s_RunningAverageSampleSize)
        {
            m_LifetimeAverage += (m_Stats / (F32)m_NumLifetimeTrials);
        } else {
            m_LifetimeAverage += (m_Stats / (F32)s_RunningAverageSampleSize) - 
                (m_LifetimeAverage / (F32)s_RunningAverageSampleSize);
        }
        m_Stats = m_ZeroStats;
    }
    
    /// predict what stats would be w/o death
    void Stats::predictStats(int timeAlive, int fullLife )
    {
        //get the local duration of life that we've lived
        int localTimeAlive = timeAlive % fullLife;

        //we can't predict if time is zero.
        if( localTimeAlive == 0 )
            return;

        //we if have already lived a full life, no need to predict
        if( localTimeAlive >= fullLife )
            return;

        F32 predict = (F32)fullLife / localTimeAlive;

        //predict the stats
        m_Stats = m_Stats * predict;
    }
    
    // Stat-tallying methods
    void Stats::tally(Reward sample)
    {
        m_Stats += sample;
    }
    
    /// Stat-retrieval methods
    Reward Stats::getStats()
    {
        return m_Stats;
    }
    
    std::ostream& operator<<(std::ostream& output, const PyNetwork& net)
    {
        output << net.mNetwork;
        return output;
    }
    
    std::ostream& operator<<(std::ostream& output, const PyOrganism& org)
    {
        output << org.mOrganism;
        return output;
    }
}
