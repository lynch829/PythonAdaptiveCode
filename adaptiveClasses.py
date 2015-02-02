__author__ = 'troy'

from scipy import io
import scipy.sparse as sps
import numpy as np
from gurobipy import *



# Data class
class imrt_data(object):
    def __init__(self, inputFilename):
        matFile = io.loadmat(inputFilename)
        self.nVox, self.nBix, self.nDijs, self.nStructs = int(matFile['nvox']), int(matFile['nbixel']), int(
            matFile['numdijs']), int(matFile['numstructs'])
        self.numoars, self.numtargets, self.oars, self.targets = int(matFile['numoars']), int(
            matFile['numtargets']), np.array(matFile['oars']).flatten(), np.array(matFile['targets']).flatten()
        bixe = np.array(matFile['bixe2_new']).flatten() - 1
        voxe = np.array(matFile['voxe2_new_nvox']).flatten() - 1
        dijs = np.array(matFile['dijs2_new']).flatten()
        self.Dmat = sps.csr_matrix((dijs, (bixe, voxe)), shape=(self.nBix, self.nVox))
        self.maskValue = np.array(matFile['maskValue']).flatten()
        self.structPerVoxel = np.array(matFile['structs']).flatten()
        self.pickstructs = map(str, matFile['pickstructs'])
        self.stageOneFraction = 0.2  # todo read this in from data file


        self.structBounds = np.array(matFile['structurebounds'])
        self.structGamma = np.array(matFile['eudweights']).flatten()

        # todo read in scenario data file location and data file
        self.numscenarios = 2
        self.scneariovalues = np.array([1.2, 2.3])


class scenario(object):
    def __init__(self, data, num, m, z1dose):
        assert (isinstance(data, imrt_data))
        self.num = num
        self.scenValue = data.scneariovalues[self.num]
        print 'building scenario', self.num
        # build dose variables
        self.z2 = [m.addVar(lb=-GRB.INFINITY, vtype=GRB.CONTINUOUS) for j in xrange(data.nVox)]
        m.update()
        #initialize dose constraint
        self.doseConstr2 = [m.addConstr(-self.z2[j], GRB.EQUAL, 0) for j in xrange(data.nVox)]
        m.update()
        #add in beamlet intensities
        self.x2 = [m.addVar(lb=0, vtype=GRB.CONTINUOUS,
                            column=Column(np.array(data.Dmat.getrow(i).todense()).flatten().tolist(), self.doseConstr2),
                            name='x2_' + str(self.num) + '_' + str(i))
                   for i in xrange(data.nBix)]
        m.update()
        self.zS = [m.addVar(lb=-GRB.INFINITY, vtype=GRB.CONTINUOUS) for j in xrange(data.nVox)]
        m.update()
        self.zLinkingConstraint = [m.addConstr(self.zS[j], GRB.EQUAL,
                                               data.stageOneFraction * z1dose[j] + (1 - data.stageOneFraction) *
                                               self.z2[j], name="zlinking") for j in range(data.nVox)]
        m.update()






# Model class
class imrt_stochastic_model(object):
    def __init__(self, inputFilename):
        # Build data
        self.data = imrt_data(inputFilename)
        assert (isinstance(self.data, imrt_data))  # makes pycharm see the instance of data and helps with development
        # initialize gurobi model
        print 'Initializing Gurobi Model'
        self.m = Model('imrt_stoch')

        # Build stage 1 gurobi variables (x,z) and dose constraint
        print 'Building Stage 1 Gurobi Variables'
        self.z1 = [self.m.addVar(lb=-GRB.INFINITY, vtype=GRB.CONTINUOUS) for i in xrange(self.data.nVox)]
        self.m.update()
        print 'Building Stage-one Dose Constraint'
        self.doseConstr1 = [self.m.addConstr(-self.z1[j], GRB.EQUAL, 0) for j in xrange(self.data.nVox)]
        self.m.update()
        print 'Populating Stage-one Dose Constraint'
        self.x1 = [self.m.addVar(lb=0, vtype=GRB.CONTINUOUS,
                                 column=Column(np.array(self.data.Dmat.getrow(i).todense()).flatten().tolist(),
                                               self.doseConstr1)) for i in xrange(self.data.nBix)]
        self.m.update()
        print 'Stage-one Dose Constraint Built'




        # todo initizlize structures
        self.structures = [imrt_structure(self.data, s) for s in range(1, self.data.nStructs + 1)]

        #todo Initialize scenarios (which build other gurobi variables for overall Zs)
        self.scenarios = [scenario(self.data, s, self.m, self.z1) for s in range(self.data.numscenarios)]

        #todo build all structure constraints (as a structure method)

        #todo initizlize stochastic class

        # Uncomment to write out model
        # print 'Writing out model'
        # self.m.write('out.lp')
        # print 'Model writing done'


    def callSolver(self):
        self.m.optimize()

        # todo make function that builds bounds for each structure (sets of bounds: Z1, Z2S, ZS, min mean max eud)


# Structure class
class imrt_structure(object):
    def __init__(self, data, index):
        assert (isinstance(data, imrt_data))
        self.name = data.pickstructs[
            index - 1]  # ASSUMES ANAT INDEXING STARTS AT 1 TODO FIX THIS SO IT STARTS AT 0, also below and elsewhere
        self.index = index
        self.voxels = np.where(data.structPerVoxel == index)[0]
        self.size = self.voxels.size
        self.z1bounds = data.structBounds[index - 1, 0:4]
        self.z2bounds = data.structBounds[index - 1, 4:8]
        self.zSbounds = data.structBounds[index - 1, 8:12]

    def buildConstraints(self, data, m, z1dose, scenarios):
        # for each set of bounds, for each bound value (if >0), build constraint
        assert (isinstance(scenarios, scenario))
        print 'Generating bounds for z1'
        #z1bounds
        for b in range(len(self.z1bounds)):
            if self.z1bounds[b] > 0 and b == 0:
                #min constraint
                self.buildMinBound(z1dose, m, self.z1bounds[b])

            elif self.z1bounds[b] > 0 and b == 1:
                # mean constraint
                self.buildMeanBound(z1dose, m, self.z1bounds[b])

            elif self.z1bounds[b] > 0 and b == 2:
                # max constraint
                self.buildMaxBound(z1dose, m, self.z1bounds[b])

            elif self.z1bounds[b] > 0 and b == 4:
                self.z1eud = self.buildEUDBound(z1dose, m, self.z1bounds[b], data)
        print 'Generating bounds for z2'
        # z2bounds
        for b in range(len(self.z2bounds)):
            if self.z2bounds[b] > 0 and b == 0:
                #min constraint
                self.buildMinBound(scenarios.z2, m, self.z2bounds[b])

            elif self.z2bounds[b] > 0 and b == 1:
                #mean constraint
                self.buildMeanBound(scenarios.z2, m, self.z2bounds[b])

            elif self.z2bounds[b] > 0 and b == 2:
                #max constraint
                self.buildMaxBound(scenarios.z2, m, self.z2bounds[b])

            elif self.z2bounds[b] > 0 and b == 4:
                self.z2eud = self.buildEUDBound(scenarios.z2, m, self.z2bounds[b], data)

        print 'Generating bounds for zS'
        #zSbounds
        for b in range(len(self.zSbounds)):
            if self.zSbounds[b] > 0 and b == 0:
                #min constraint
                self.buildMinBound(scenarios.zS, m, self.zSbounds[b])

            elif self.zSbounds[b] > 0 and b == 1:
                #mean constraint
                self.buildMeanBound(scenarios.zS, m, self.zSbounds[b])

            elif self.zSbounds[b] > 0 and b == 2:
                #max constraint
                self.buildMaxBound(scenarios.zS, m, self.zSbounds[b])

            elif self.zSbounds[b] > 0 and b == 4:
                self.zSeud = self.buildEUDBound(scenarios.zS, m, self.zSbounds[b], data)


    def buildMinBound(self, doseVector, m, bound):
        print "Building min bound on structure", self.index
        for j in range(self.size):
            doseVector[self.index[j]].setAttr("LB", bound)
        m.update()

    def buildMaxBound(self, doseVector, m, bound):
        print "Building max bound on structure", self.index
        for j in range(self.size):
            doseVector[self.index[j]].setAttr("UB", bound)
        m.update()

    def buildMeanBound(self, doseVector, m, bound):
        print "Building mean bound on structure", self.index
        meanHolderVar = m.addVar(lb=-GRB.INFINITY, ub=bound, vtype=GRB.CONTINUOUS)
        m.update()
        m.addConstr(quicksum(doseVector[self.index[j]] for j in range(self.size)) == meanHolderVar)
        m.update()

    def buildEUDBound(self, doseVector, m, bound, data):
        print "Building eud bound on structure", self.index
        assert (isinstance(data, imrt_data))
        # build mean holder
        meanHolderVar = m.addVar(lb=-GRB.INFINITY, vtype=GRB.CONTINUOUS)
        m.update()
        m.addConstr(quicksum(doseVector[self.index[j]] for j in range(self.size)), GRB.EQUAL, meanHolderVar)
        m.update()
        # build upper or lower bound
        boundHolderVar = m.addVar(lb=0, vtype=GRB.CONTINUOUS)
        if self.index in data.targets:
            for j in range(self.size):
                m.addConstr(boundHolderVar, GRB.LESS_EQUAL, doseVector[self.index[j]])
            doseEUD = m.addVar(lb=bound, vtype=GRB.CONTINUOUS)
        else:
            for j in range(self.size):
                m.addConstr(boundHolderVar, GRB.GREATER_EQUAL, doseVector[self.index[j]])
            doseEUD = m.addVar(lb=0, ub=bound, vtype=GRB.CONTINUOUS)
        m.update()
        m.addConstr(doseEUD, GRB.EQUAL, data.structGamma[self.index - 1] * meanHolderVar + (
        1 - data.structGamma[self.index - 1]) * boundHolderVar)
        m.update()
        return doseEUD

# adaLung class

# todo reads in separate data file

































