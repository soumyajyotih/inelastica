print "SVN $Id$"

"""
################################################################

 python TBTrans 
 Magnus Paulsson magnus.paulsson@hik.se

 Requires: numpy (compile it linked with mkl, acml or atlas!)
           ScientificPython (vers. >= 2.8)
           For speed compile the fortran subroutines in F90 
           (cd F90;source compile.bat)

  UNITS! Always eV and Angstrom!
         k-values always given in range [0,1.0] (or [-0.5,0.5])
         They are not in reciprocal space. Instead they corresponds
         to the mathematical orthogonal space that is fourier 
         transformed.

################################################################
"""


import SiestaIO as SIO
import MiscMath as MM
import NEGF
import numpy as N
import numpy.linalg as LA
import sys, string
from optparse import OptionParser, OptionGroup
try:
    import scipy.linalg as SLA 
    hasSciPy = True
except:
    hasSciPy = False 

################### Help functions ############################
try:
    import F90helpers as F90
    F90imported = True
except:
    F90imported = False
    print "########################################################"
    print "Perhaps time to compile F90/setkpointhelper"
    print "Try:" 
    print "        cd F90;source compile.bat"
    print "########################################################"



################### Main program ############################
def main(pyTBT=True,deviceRegion=[0,0],fn=None):
    """
    Running standalone to calculate transmission 
    *OR* 
      called from Eigenchannels or Inelastica 
      returning elecL, elecR, GF, deviceStart, deviceEnd
    """
    
    if pyTBT: 
        usage = "usage: %prog RUN.fdf"
        descr = "pyTBT is the Python version of TBtrans originally developed by Mads Brandbyge."
        intro = """
pyTBT is the Python version of TBtrans originally developed by Mads Brandbyge.

pyTBT reads some of the TBT and TS keywords from the fdf file:

Electrodes:
TS.HSFileLeft         filename.TSHS
TS.ReplicateA1Left    1
TS.ReplicateA2Left    1
TS.HSFileRight        filename.TSHS
TS.ReplicateA1Right   1
TS.ReplicateA2Right   1
Note: Fredericos TBtrans and the Transiesta version planned to be release in 2009 cannot use ReplicateA1,2 but pyTBT can.

Device region:
TS.TBT.PDOSFrom       10       [default=1]
TS.TBT.PDOSTo         20       [default=last atom]
Note: If you just want transmission pyTBT is quickest if the device region
      is the middle 1/3 of the orbitals.

Transmission energies [default]:
TS.TBT.NPoints        21              
TS.TBT.Emin          -1.000000 eV  
TS.TBT.Emax           1.000000 eV 

How self-energies are applied:
TS.UseBulkInElectrodes .True.
Note, False for this option does not seem to be a good choice.

NEW KEYWORDS:
pyTBT.eta             0.000001 eV [default, imaginary part of energy]

Kpoint sampling of transmission:
pyTBT.K_A1            1           [default=1]
pyTBT.K_A2            1


Ouputfiles:
SystemLabel[.UP/.DOWN].TRANS     Transmission k-point dependent.
SystemLabel[.UP/.DOWN].AVTRANS   Averaged over k-points.

"""
        parser = OptionParser(usage,description=descr)
        print intro
        parser.parse_args()

    # Read options
    ##############################################################################
    if fn==None:
        try: 
            fn = sys.argv[1]
            print "pyTBT reading keywords from ",fn
        except:
            fn = 'RUN.fdf'
            print "pyTBT::WARNING reading keywords from default file : ",fn

    # Electrodes
    fnL  =SIO.GetFDFlineWithDefault(fn,'TS.HSFileLeft', str, None, 'pyTBT')
    NA1L =SIO.GetFDFlineWithDefault(fn,'TS.ReplicateA1Left', int, 1, 'pyTBT')
    NA2L =SIO.GetFDFlineWithDefault(fn,'TS.ReplicateA2Left', int, 1, 'pyTBT')
    fnR  =SIO.GetFDFlineWithDefault(fn,'TS.HSFileRight', str, None, 'pyTBT')
    NA1R =SIO.GetFDFlineWithDefault(fn,'TS.ReplicateA1Right', int, 1, 'pyTBT')
    NA2R =SIO.GetFDFlineWithDefault(fn,'TS.ReplicateA2Right', int, 1, 'pyTBT')

    # Device region
    if deviceRegion[0]==0:
        devSt =SIO.GetFDFlineWithDefault(fn,'TS.TBT.PDOSFrom', int, 0, 'pyTBT')
    else:
        devSt=deviceRegion[0]
    if deviceRegion[1]==0:
        devEnd=SIO.GetFDFlineWithDefault(fn,'TS.TBT.PDOSTo', int, 0, 'pyTBT')
    else:
        devEnd=deviceRegion[1]

    # Voltage
    voltage  =SIO.GetFDFlineWithDefault(fn,'TS.Voltage', float, 0.0, 'pyTBT')

    # Energy range
    nE  =SIO.GetFDFlineWithDefault(fn,'TS.TBT.NPoints', int, 21, 'pyTBT')
    minE=SIO.GetFDFlineWithDefault(fn,'TS.TBT.Emin', float, -1.0, 'pyTBT')
    maxE=SIO.GetFDFlineWithDefault(fn,'TS.TBT.Emax', float, 1.0, 'pyTBT')
    if nE>1:
        dE = (maxE-minE)/float(nE-1)
        Elist = N.array(range(int((maxE-minE+1e-9)/dE)+1),N.float)*dE+minE
    else:
        dE=0.0
        Elist=N.array((minE,),N.float)

    UseBulk=SIO.GetFDFlineWithDefault(fn,'TS.UseBulkInElectrodes', bool, True, 'pyTBT')

    eta=SIO.GetFDFlineWithDefault(fn,'pyTBT.eta', float, 0.000001, 'pyTBT')
    Nk1=SIO.GetFDFlineWithDefault(fn,'pyTBT.K_A1', int, 1, 'pyTBT')
    Nk2=SIO.GetFDFlineWithDefault(fn,'pyTBT.K_A2', int, 1, 'pyTBT')

    outFile=SIO.GetFDFlineWithDefault(fn,'SystemLabel', str, None, 'pyTBT')

    #=SIO.GetFDFlineWithDefault(fn,'', int, , 'pyTBT')

    ##############################################################################
    # Define electrodes and device

    elecL = NEGF.ElectrodeSelfEnergy(fnL,NA1L,NA2L,voltage/2.)
    elecR = NEGF.ElectrodeSelfEnergy(fnR,NA1R,NA2R,-voltage/2.)
    myGF = NEGF.GF(outFile+'.TSHS',elecL,elecR,Bulk=UseBulk,DeviceAtoms=[devSt, devEnd])
    nspin = myGF.HS.nspin
    if devSt==0:
        devSt=GF.DeviceAtoms[0]
    if devEnd==0:
        devEnd=GF.DeviceAtoms[1]
        
    print """
##############################################################
pyTBT

Energy [eV]                     : %f:%f:%f
kpoints                         : %i, %i 
eta [eV]                        : %f 
Device [Atoms Siesta numbering] : %i:%i 
Bulk                            : %s
SpinPolarization                : %i
Voltage                         : %f
##############################################################

"""%(minE,dE,maxE,Nk1,Nk2,eta,devSt,devEnd,UseBulk,nspin,voltage)

    channels = 10
    Tkpt=N.zeros((len(Elist),Nk1,Nk2,channels+1),N.float)
    outFile += '.%ix%i'%(Nk1,Nk2)
    for iSpin in range(nspin):
        if nspin<2:
            fo=open(outFile+'.AVTRANS','write')
        else:
            fo=open(outFile+['.UP','.DOWN'][iSpin]+'.AVTRANS','write')
        fo.write('# E   Ttot(E)   Ti(E) (i=1-10)\n')
        for ie, ee in enumerate(Elist):
            Tavg = N.zeros(channels+1,N.float)
            for ik1 in range(Nk1):
                for ik2 in range(Nk2):
                    kpt=N.array([ik1/float(Nk1),ik2/float(Nk2)],N.float)
                    myGF.calcGF(ee+eta*1.0j,kpt,ispin=iSpin)
                    T = myGF.calcT(channels)
                    Tavg += T/Nk1/Nk2
                    Tkpt[ie,ik1,ik2] = T
            print ee, Tavg
            transline = '\n%.10f '%ee
            for ichan in range(channels+1):
                transline += '%.4e '%Tavg[ichan]
            fo.write(transline)
        fo.close()
        
        # Write k-point transmission
        if nspin<2:
            fo=open(outFile+'.TRANS','write')
        else:
            fo=open(outFile+['.UP','.DOWN'][iSpin]+'.TRANS','write')
        for ik1 in range(Nk1):
            for ik2 in range(Nk2):
                fo.write('\n\n# k = %f, %f '%(ik1/float(Nk1),ik2/float(Nk2)))
                for ie, ee in enumerate(Elist):
                    transline = '\n%.10f '%ee
                    for ichan in range(channels+1):
                        transline += '%.4e '%Tkpt[ie,ik1,ik2,ichan]
                    fo.write(transline)
        fo.close()


if __name__ == '__main__':
    main()
