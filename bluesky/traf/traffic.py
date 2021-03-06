import numpy as np
from math import *

from ..tools.aero import fpm, kts, ft, nm, g0,  tas2eas, tas2mach, tas2cas, mach2tas,  \
                         mach2cas, cas2tas, cas2mach, Rearth

from ..tools.aero_np import vatmos, vcas2tas, vtas2cas,  vtas2mach, vcas2mach,\
                            vmach2tas, qdrdist
from ..tools.misc import degto180, kwikdist
from ..tools.datalog import Datalog

from route import Route
from params import Trails
from adsbmodel import ADSBModel

from asas import Dbconf
from asas_LOS import Dbconf2    #  LOS 
from ..tools.datalog import Datalog #Datalogger Thom


from .. import settings
import pdb

try:
    if settings.performance_model == 'bluesky':
        from perf import Perf

    elif settings.performance_model == 'bada':
        from perfbada import PerfBADA as Perf

except ImportError as err:
    print err.args[0]
    print 'Falling back to BlueSky performance model'
    from perf import Perf


class Traffic:
    """
    Traffic class definition    : Traffic data

    Methods:
        Traffic()            :  constructor
        reset()              :  Reset traffic database w.r.t a/c data

        create(acid,actype,aclat,aclon,achdg,acalt,acspd) : create aircraft
        delete(acid)         : delete an aircraft from traffic data
        deletall()           : delete all traffic
        update(sim)          : do a numerical integration step
        id2idx(name)         : return index in traffic database of given call sign
        selhdg(i,hdg)        : set autopilot heading and activate heading select mode 
        selspd(i,spd)        : set autopilot CAS/Mach and activate heading select mode 

        engchange(i,engtype) : change engine type of an aircraft

        changeTrailColor(color,idx)     : change colour of trail of aircraft idx
 
        setNoise(A)          : Add turbulence

    Members: see create

    Created by  : Jacco M. Hoekstra
    """

    def __init__(self, navdb):

        self.reset(navdb)
        return

    def reset(self, navdb):
        self.dts = []
        self.ntraf = 0

        #  model-specific parameters.
        # Default: BlueSky internal performance model.
        # Insert your BADA files to the folder "BlueSky/data/coefficients/BADA"
        # for working with EUROCONTROL`s Base of Aircraft Data revision 3.12

        self.perf = Perf(self)

        self.dts = []

        self.ntraf = 0

        # Create datalog instance
        self.log = Datalog()
        

        # Traffic list & arrays definition

        # !!!IMPORTANT NOTE!!!
        # Any variables added here should also be added in the Traffic
        # methods self.create() (append) and self.delete() (delete)
        # which can be found directly below __init__

        # Traffic basic flight data

        # Traffic basic flight data
        self.id     = []  # identifier (string)
        self.type   = []  # aircaft type (string)
        self.lat    = np.array([])  # latitude [deg]
        self.lon    = np.array([])  # longitude [deg]
        self.trk    = np.array([])  # track angle [deg]
        self.tas    = np.array([])  # true airspeed [m/s]
        self.gs     = np.array([])  # ground speed [m/s]
        self.cas    = np.array([])  # calibrated airspeed [m/s]
        self.M      = np.array([])  # mach number
        self.alt    = np.array([])  # altitude [m]
        self.fll    = np.array([])  # flight level [ft/100]
        self.vs     = np.array([])  # vertical speed [m/s]
        self.p      = np.array([])  # atmospheric air pressure [N/m2]
        self.rho    = np.array([])  # atmospheric air density [kg/m3]
        self.Temp   = np.array([])  # atmospheric air temperature [K]
        self.dtemp  = np.array([])  # delta t for non-ISA conditions
        
        #thom
        self.createtime=np.array([])
        self.timer=np.float32(0)

        # Traffic performance data
        self.avsdef = np.array([])  # [m/s]default vertical speed of autopilot
        self.aphi   = np.array([])  # [rad] bank angle setting of autopilot
        self.ax     = np.array([])  # [m/s2] absolute value of longitudinal accelleration
        self.bank   = np.array([])  # nominal bank angle, [radian]
        self.bphase = np.array([])  # standard bank angles per phase
        self.hdgsel = np.array([])  # determines whether aircraft is turning

        # Help variables to save computation time
        self.coslat = np.array([])  # Cosine of latitude for flat-earth aproximations

        # Crossover altitude
        self.abco   = np.array([])
        self.belco  = np.array([])

        # Traffic autopilot settings
        self.ahdg   = []  # selected heading [deg]
        self.aspd   = []  # selected spd(CAS) [m/s]
        self.aptas  = []  # just for initializing
        self.ama    = []  # selected spd above crossover altitude (Mach) [-]
        self.aalt   = []  # selected alt[m]
        self.afll   = []  # selected fl [ft/100]
        self.avs    = []  # selected vertical speed [m/s]

        # limit settings
        self.lspd   = []  # limit speed
        self.lalt   = []  # limit altitude
        self.lvs    = []  # limit vertical speed due to thrust limitation

        # Traffic navigation information
        self.orig   = []  # Four letter code of origin airport
        self.dest   = []  # Four letter code of destination airport

        # LNAV route navigation
        self.swlnav = np.array([])  # Lateral (HDG) based on nav?
        self.swvnav = np.array([])  # Vertical/longitudinal (ALT+SPD) based on nav info

        self.actwplat  = np.array([])  # Active WP latitude
        self.actwplon  = np.array([])  # Active WP longitude
        self.actwpalt  = np.array([])  # Active WP altitude to arrive at
        self.actwpspd  = np.array([])  # Active WP speed
        self.actwpturn = np.array([])  # Distance when to turn to next waypoint
        self.actwpflyby = np.array([])  # Distance when to turn to next waypoint
      

        # VNAV variablescruise level
        self.crzalt  = np.array([])    # Cruise altitude[m]
        self.dist2vs = np.array([])    # Distance to start V/S of VANAV
        self.actwpvs = np.array([])    # Actual V/S to use

        # Route info
        self.route = []

        # ASAS info per aircraft:
        self.iconf      = []            # index in 'conflicting' aircraft database
        self.iconf2     = []
        self.asasactive = np.array([])  # whether the autopilot follows ASAS or not
        self.asashdg    = np.array([])  # heading provided by the ASAS [deg]
        self.asasspd    = np.array([])  # speed provided by the ASAS (eas) [m/s]
        self.asasalt    = np.array([])  # speed alt by the ASAS [m]
        self.asasvsp    = np.array([])  # speed vspeed by the ASAS [m/s]

        self.desalt     = np.array([])  # desired altitude [m]
        self.deshdg     = np.array([])  # desired heading
        self.desvs      = np.array([])  # desired vertical speed [m/s]
        self.desspd     = np.array([])  # desired speed [m/s]

        # Display information on label
        self.label      = []  # Text and bitmap of traffic label
        self.trailcol   = []  # Trail color: default 'Blue'

        # Transmitted data to other aircraft due to truncated effect
        self.adsbtime   = np.array([])
        self.adsblat    = np.array([])
        self.adsblon    = np.array([])
        self.adsbalt    = np.array([])
        self.adsbtrk    = np.array([])
        self.adsbtas    = np.array([])
        self.adsbgs     = np.array([])
        self.adsbvs     = np.array([])

        self.inconflict = np.array([], dtype=bool)

        #-----------------------------------------------------------------------------
        # Not per aircraft data

        # Scheduling of FMS and ASAS
        self.t0fms = -999.  # last time fms was called
        self.dtfms = 1.01  # interval for fms

        self.t0asas = -999.  # last time ASAS was called
        self.dtasas = 1.00  # interval for ASAS

        # Flight performance scheduling
        self.perfdt = 0.1           # [s] update interval of performance limits
        self.perft0 = -self.perfdt  # [s] last time checked (in terms of simt)
        self.warned2 = False        # Flag: Did we warn for default engine parameters yet?

        # ADS-B transmission-receiver model
        self.adsb = ADSBModel(self)

        # ASAS objects: Conflict Database
        self.dbconf = Dbconf(self, 300., 5. * nm, 1000. * ft)  # hard coded values to be replaced
        self.dbconf2 = Dbconf2(self,300., 5.*nm, 1000.*ft)  #Thom: here CDR is performed with ADSB system

        # Import navigation data base
        self.navdb  = navdb

        # Traffic area: delete traffic when it leaves this area (so not when outside)
        self.swarea    = False
        self.arealat0  = 0.0  # [deg] lower latitude defining area
        self.arealat1  = 0.0  # [deg] upper latitude defining area
        self.arealon0  = 0.0  # [deg] lower longitude defining area
        self.arealon1  = 0.0  # [deg] upper longitude defining area
        self.areafloor = -999999.0  # [m] Delete when descending through this h
        self.areadt    = 5.0  # [s] frequency of area check (simtime)
        self.areat0    = -100.  # last time checked
        self.arearadius    = 100.0 # [NM] radius of experiment area if it is a circle

        self.inside = []
        self.fir_circle_point = (0.0, 0.0)
        self.fir_circle_radius = 1.0

        # Taxi switch
        self.swtaxi = False  # Default OFF: delete traffic below 1500 ft

        # Research Area ("Square" for Square, "Circle" for Circle area)
        self.area = ""

        # Bread crumbs for trails
        self.lastlat  = []
        self.lastlon  = []
        self.lasttim  = []
        self.trails   = Trails()
        self.swtrails = False  # Default switched off

        # ADS-B Coverage area
        self.swAdsbCoverage = False

        # Noise (turbulence, ADBS-transmission noise, ADSB-truncated effect)
        self.setNoise(False)

        self.eps = np.array([])
        
        ### ---------------- Thom Variables
        
        ## Log variables
        #Flight statistics
        self.distance_2D    = np.array([])
        self.distance_3D    = np.array([])
        self.flightime      = np.array([])
        self.work           = np.array([])
        self.ACInArea       = np.array([])
                
        
       
        
        # switches
        self.SnapSwitch=False           # Snap logging
        self.ConfSwitch=False            # conflict
        self.IntSwitch=False             # Intrusion
        self.FlstSwitch=False            # Flight statistics
        self.TmxSwitch=False             # TMX switch
        self.GlobSwitch=False
        
        self.GlobSwitch2=True #Keep always True; Switch for logging global variables only once
        
        # constants
        # timer inteval for writing
        self.t0writelog = -999  # Last time Writelog was called
        self.dtwritelog = 180 # Interval fot writing data and clear buffer
        # Individual loggers
        #Snap
        self.Snapt0=-999    # Last time
        self.Snapdt=30.00   # Snapshot interval
        #Conf
        self.Conft0=-999    # Last time
        self.Confdt=1       # Conf interval
        #Int
        self.Intt0=-999     # Last time 
        self.Intdt=1        # Intrusion interval
        #Flst
        self.Flstt0=-999     # Last time 
        self.Flstdt=30        # statistics
        
        #TMX
        self.Tmxt0=-999     # Last time 
        self.Tmxdt=10        # tmx

        #TMX
        self.Globt0=-999     # Last time 
        self.Globdt=30        # Glob interval        
        
        
        ## Delete/Experiment Area variables
        self.CreateStart = 1800
        self.CreateEnd = 3600
        # start and stop time for logging
        self.ExperimentStart = 1800  #Time to start logging
        self.ExperimentEnd = 4200 # Time to end logging
        self.ExperimentRadius = 94.5 #Experiment radius in NM
        #Global
        self.t0Delete =  -999.          # Initial Value
        self.dtDelete = 3               # Delta T to check for deleting AC (now at 3 s)
        self.DeleteSwitch=True
        self.DeleteCenterLatLon=[0,0]          # Center location to compare distance with this lat/lon
        self.DeleteDistance= 94.5         # NM
        #per AC
        self.DistanceList=np.array([])
        self.DeleteIdx=[]
        
       
        
        

        return

    def create(self, acid, actype, aclat, aclon, achdg, acalt, casmach):
        """Create an aircraft"""
        # Check if not already exist
        if self.id.count(acid.upper()) > 0:
            return False,acid+" already exists." # already exists do nothing

        # Increase number of aircraft
        self.ntraf = self.ntraf + 1

        # Convert speed
        if 0.1 < casmach < 1.0 :
            acspd = mach2tas(casmach, acalt)
        else:
            acspd = cas2tas(casmach * kts, acalt)

        # Process input
        self.id.append(acid.upper())
        self.type.append(actype)
        self.lat   = np.append(self.lat, aclat)
        self.lon   = np.append(self.lon, aclon)
        self.trk   = np.append(self.trk, achdg)  # TBD: add conversion hdg => trk
        self.alt   = np.append(self.alt, acalt)
        self.fll   = np.append(self.fll, (acalt)/(100 * ft))
        self.vs    = np.append(self.vs, 0.)
        c_temp, c_rho, c_p = vatmos(acalt)
        self.p     = np.append(self.p, c_p)
        self.rho   = np.append(self.rho, c_rho)
        self.Temp  = np.append(self.Temp, c_temp)
        self.dtemp = np.append(self.dtemp, 0)  # at the moment just ISA conditions
        self.tas   = np.append(self.tas, acspd)
        self.gs    = np.append(self.gs, acspd)
        self.cas   = np.append(self.cas, tas2cas(acspd, acalt))
        self.M     = np.append(self.M, tas2mach(acspd, acalt))
        
        
        self.createtime=np.append(self.createtime,self.timer) # Time AC is created

        # AC is initialized with neutral max bank angle
        self.bank = np.append(self.bank, radians(25.))
        if self.ntraf < 2:
            self.bphase = np.deg2rad(np.array([15, 35, 35, 35, 15, 45]))
        self.hdgsel = np.append(self.hdgsel, False)

        #------------------------------Performance data--------------------------------
        # Type specific data
        #(temporarily default values)
        self.avsdef = np.append(self.avsdef, 1500. * fpm)  # default vertical speed of autopilot
        self.aphi   = np.append(self.aphi, radians(25.))  # bank angle setting of autopilot
        self.ax     = np.append(self.ax, kts)  # absolute value of longitudinal accelleration

        # Crossover altitude
        self.abco   = np.append(self.abco, 0)
        self.belco  = np.append(self.belco, 1)

        # performance data
        self.perf.create(actype)

        # Traffic autopilot settings: hdg[deg], spd (CAS,m/s), alt[m], vspd[m/s]
        self.ahdg = np.append(self.ahdg, achdg)  # selected heading [deg]
        self.aspd = np.append(self.aspd, tas2cas(acspd, acalt))  # selected spd(cas) [m/s]
        self.aptas = np.append(self.aptas, acspd) # [m/s]
        self.ama  = np.append(self.ama, 0.) # selected spd above crossover (Mach) [-]
        self.aalt = np.append(self.aalt, acalt)  # selected alt[m]
        self.afll = np.append(self.afll, (acalt/100)) # selected fl[ft/100]
        self.avs = np.append(self.avs, 0.)  # selected vertical speed [m/s]
        
        # limit settings: initialize with 0
        self.lspd = np.append(self.lspd, 0.0)
        self.lalt = np.append(self.lalt, 0.0)
        self.lvs = np.append(self.lvs, 0.0)

        # Help variables to save computation time
        self.coslat = np.append(self.coslat,cos(radians(aclat)))  # Cosine of latitude for flat-earth aproximations

        # Traffic navigation information
        self.dest.append("")
        self.orig.append("")

        # LNAV route navigation
        self.swlnav = np.append(self.swlnav, False)  # Lateral (HDG) based on nav
        self.swvnav = np.append(self.swvnav, False)  # Vertical/longitudinal (ALT+SPD) based on nav info

        self.actwplat  = np.append(self.actwplat, 89.99)  # Active WP latitude
        self.actwplon  = np.append(self.actwplon, 0.0)   # Active WP longitude
        self.actwpalt  = np.append(self.actwpalt, 0.0)   # Active WP altitude
        self.actwpspd  = np.append(self.actwpspd, -999.)   # Active WP speed
        self.actwpturn = np.append(self.actwpturn, 1.0)   # Distance to active waypoint where to turn
        self.actwpflyby = np.append(self.actwpflyby, 1.0)   # Flyby/fly-over switch

        # VNAV cruise level
        self.crzalt = np.append(self.crzalt,-999.) # Cruise altitude[m] <0=None
        self.dist2vs = np.append(self.dist2vs,-999.)  # Distance to start V/S of VANAV
        self.actwpvs = np.append(self.actwpvs,0.0)    # Actual V/S to use then

        # Route info
        self.route.append(Route(self.navdb))  # create empty route connected with nav databse

        eas = tas2eas(acspd, acalt)

        # ASAS info: no conflict => -1
        self.iconf.append(-1)  # index in 'conflicting' aircraft database
        self.iconf2.append(-1)
        # ASAS output commanded values
        self.asasactive = np.append(self.asasactive, False)
        self.asashdg = np.append(self.asashdg, achdg)
        self.asasspd = np.append(self.asasspd, eas)
        self.asasalt = np.append(self.asasalt, acalt)
        self.asasvsp = np.append(self.asasvsp, 0.)

        self.desalt  = np.append(self.desalt, acalt)
        self.desvs   = np.append(self.desvs, 0.0)
        self.desspd  = np.append(self.desspd, eas)
        self.deshdg  = np.append(self.deshdg, achdg)

        # Area variable set to False to avoid deletion upon creation outside
        self.inside.append(False)

        # Display information on label
        self.label.append(['', '', '', 0])

        # Bread crumbs for trails
        self.trailcol.append(self.trails.defcolor)
        self.lastlat = np.append(self.lastlat, aclat)
        self.lastlon = np.append(self.lastlon, aclon)
        self.lasttim = np.append(self.lasttim, 0.0)

        # ADS-B Coverage area
        self.swAdsbCoverage = False
        
        # Transmitted data to other aircraft due to truncated effect
        self.adsbtime=np.append(self.adsbtime,np.random.rand(self.trunctime))
        self.adsblat=np.append(self.adsblat,aclat)
        self.adsblon=np.append(self.adsblon,aclon)
        self.adsbalt=np.append(self.adsbalt,acalt)
        self.adsbtrk=np.append(self.adsbtrk,achdg)
        self.adsbtas=np.append(self.adsbtas,acspd)
        self.adsbgs=np.append(self.adsbgs,acspd)
        self.adsbvs=np.append(self.adsbvs,0.)
        
        self.inconflict=np.append(self.inconflict,False)        
        
        self.eps = np.append(self.eps, 0.01)
        
        # For ADSB module
        self.adsb.create(acid, actype, aclat, aclon, achdg, acalt, acspd) #Thom
        # Flight Statistics data
        self.distance_2D    = np.append(self.distance_2D,0.)
        self.distance_3D    = np.append(self.distance_3D,0.)
        self.flightime      = np.append(self.flightime,0.)
        self.work           = np.append(self.work,0.)
        
        self.ACInArea       = np.append(self.ACInArea,False)

        return True

    def delete(self, acid):
        """Delete an aircraft"""

        # Look up index of aircraft
        idx = self.id2idx(acid)
        
        # Do nothing if not found
        if idx<0:
            return False
            
        self.adsb.delete(idx) #Thom 
        
        del self.id[idx]
        del self.type[idx]

        # Traffic basic data
        self.lat    = np.delete(self.lat, idx)
        self.lon    = np.delete(self.lon, idx)
        self.trk    = np.delete(self.trk, idx)
        self.alt    = np.delete(self.alt, idx)
        self.fll    = np.delete(self.fll, idx)
        self.vs     = np.delete(self.vs, idx)
        self.tas    = np.delete(self.tas, idx)
        self.gs     = np.delete(self.gs, idx)
        self.cas    = np.delete(self.cas, idx)
        self.M      = np.delete(self.M, idx)

        self.p      = np.delete(self.p, idx)
        self.rho    = np.delete(self.rho, idx)
        self.Temp   = np.delete(self.Temp, idx)
        self.dtemp  = np.delete(self.dtemp, idx)
        self.hdgsel = np.delete(self.hdgsel, idx)
        self.bank   = np.delete(self.bank, idx)

        # Crossover altitude
        self.abco   = np.delete(self.abco, idx)
        self.belco  = np.delete(self.belco, idx)

        # Type specific data (temporarily default values)
        self.avsdef = np.delete(self.avsdef, idx)
        self.aphi   = np.delete(self.aphi, idx)
        self.ax     = np.delete(self.ax, idx)

        # performance data
        self.perf.delete(idx)

        # Traffic autopilot settings: hdg[deg], spd (CAS,m/s), alt[m], vspd[m/s]
        self.ahdg   = np.delete(self.ahdg, idx)
        self.aspd   = np.delete(self.aspd, idx)
        self.ama    = np.delete(self.ama, idx)
        self.aptas  = np.delete(self.aptas, idx)
        self.aalt   = np.delete(self.aalt, idx)
        self.afll   = np.delete(self.afll, idx)
        self.avs    = np.delete(self.avs, idx)

        # limit settings
        self.lspd   = np.delete(self.lspd, idx)
        self.lalt   = np.delete(self.lalt, idx)
        self.lvs    = np.delete(self.lvs, idx)

        # Help variables to save computation time
        self.coslat = np.delete(self.coslat,idx)  # Cosine of latitude for flat-earth aproximations

        # Traffic navigation variables
        del self.dest[idx]
        del self.orig[idx]

        self.swlnav = np.delete(self.swlnav, idx)
        self.swvnav = np.delete(self.swvnav, idx)

        self.actwplat  = np.delete(self.actwplat,  idx)
        self.actwplon  = np.delete(self.actwplon,  idx)
        self.actwpalt  = np.delete(self.actwpalt,  idx)
        self.actwpspd  = np.delete(self.actwpspd,  idx)
        self.actwpturn = np.delete(self.actwpturn, idx)
        self.actwpflyby = np.delete(self.actwpflyby, idx)


        # VNAV cruise level
        self.crzalt    = np.delete(self.crzalt,  idx)
        self.dist2vs   = np.delete(self.dist2vs, idx)    # Distance to start V/S of VANAV
        self.actwpvs   = np.delete(self.actwpvs, idx)    # Actual V/S to use


        # Route info
        del self.route[idx]

        # ASAS output commanded values
        del self.iconf[idx]
        del self.iconf2[idx]
        self.asasactive = np.delete(self.asasactive, idx)
        self.asashdg    = np.delete(self.asashdg, idx)
        self.asasspd    = np.delete(self.asasspd, idx)
        self.asasalt    = np.delete(self.asasalt, idx)
        self.asasvsp    = np.delete(self.asasvsp, idx)

        self.desalt     = np.delete(self.desalt, idx)
        self.desvs      = np.delete(self.desvs, idx)
        self.desspd     = np.delete(self.desspd, idx)
        self.deshdg     = np.delete(self.deshdg, idx)

        # Metrics, area
        del self.inside[idx]

        # Traffic display data: label
        del self.label[idx]

        # Delete bread crumb data
        self.lastlat = np.delete(self.lastlat, idx)
        self.lastlon = np.delete(self.lastlon, idx)
        self.lasttim = np.delete(self.lasttim, idx)
        del self.trailcol[idx]

        # Transmitted data to other aircraft due to truncated effect
        self.adsbtime = np.delete(self.adsbtime, idx)
        self.adsblat  = np.delete(self.adsblat, idx)
        self.adsblon  = np.delete(self.adsblon, idx)
        self.adsbalt  = np.delete(self.adsbalt, idx)
        self.adsbtrk  = np.delete(self.adsbtrk, idx)
        self.adsbtas  = np.delete(self.adsbtas, idx)
        self.adsbgs   = np.delete(self.adsbgs, idx)
        self.adsbvs   = np.delete(self.adsbvs, idx)

        self.inconflict = np.delete(self.inconflict, idx)

        # Decrease number fo aircraft
        self.ntraf = self.ntraf - 1

        self.eps = np.delete(self.eps, idx)
        
        #Thom: Flight statistics
        self.createtime     = np.delete(self.createtime,idx)

        self.distance_2D    = np.delete(self.distance_2D,idx)
        self.distance_3D    = np.delete(self.distance_3D,idx)
        self.flightime      = np.delete(self.flightime,idx)
        self.work           = np.delete(self.work,idx)
        
        self.ACInArea       = np.append(self.ACInArea,idx)
        #End Thom
        
        return True

    def update(self, simt, simdt):
        
        self.timer=simt
        # Update only necessary if there is traffic
        if self.ntraf == 0:
            return
        self.timer=simt
#        import pdb; pdb.set_trace()
        self.dts.append(simdt)
        #---------------- Atmosphere ----------------
        self.p, self.rho, self.Temp = vatmos(self.alt)

        #-------------- Performance limits autopilot settings --------------
        # Check difference with AP settings for trafperf and autopilot
        self.delalt = self.aalt - self.alt  # [m]
        
        # below crossover altitude: CAS=const, above crossover altitude: MA = const
        # aptas hast to be calculated before delspd
        self.aptas = vcas2tas(self.aspd, self.alt)*self.belco + vmach2tas(self.ama, self.alt)*self.abco  
        #self.delspd = self.aptas - self.tas
   

        ###############################################################################
        # Debugging: add 10000 random aircraft
        #            if simt>1.0 and self.ntraf<1000:
        #                for i in range(10000):
        #                   acid="KL"+str(i)
        #                   aclat = random.random()*180.-90.
        #                   aclon = random.random()*360.-180.
        #                   achdg = random.random()*360.
        #                   acalt = (random.random()*18000.+2000.)*0.3048
        #                   self.create(acid,'B747',aclat,aclon,achdg,acalt,350.)
        #
        #################################################################################
        
        #-------------------- ADSB update: --------------------

        self.adsbtime = self.adsbtime + simdt
        if self.ADSBtrunc:
            ADSB_update = np.where(self.adsbtime>self.trunctime)
        else:
            ADSB_update = range(self.ntraf)

        for i in ADSB_update:
            self.adsbtime[i] = self.adsbtime[i] - self.trunctime
            self.adsblat[i]  = self.lat[i]
            self.adsblon[i]  = self.lon[i]
            self.adsbalt[i]  = self.alt[i]
            self.adsbtrk[i]  = self.trk[i]
            self.adsbtas[i]  = self.tas[i]
            self.adsbgs[i]   = self.gs[i]
            self.adsbvs[i]   = self.vs[i]

        # New version ADSB Model
        self.adsb.update(simt)        

        #------------------- ASAS update: ---------------------
        # Scheduling: when dt has passed or restart:
        if self.t0asas+self.dtasas<simt or simt<self.t0asas \
            and self.dbconf.swasas:
            self.t0asas = simt
            # Save old result
            iconf0 = np.array(self.iconf)

        
            #Based on real loc, doeson't resolve
            self.dbconf2.detect(simt)
            self.dbconf2.conflictlist(simt)
#            if np.count_nonzero(self.asasactive)>0:
#                import pdb
#                pdb.set_trace()

            
            self.dbconf.detect()
            #self.dbconf.conflictfilter(simt)
            self.dbconf.conflictlist(simt)
            self.dbconf.APorASAS()  
            self.dbconf.resolve()

            # Reset label because of colour change
            chnged = np.where(iconf0!=np.array(self.iconf))[0]
            for i in chnged:
                self.label[i]=[" "," ", ""," "]


        #-----------------  FMS GUIDANCE & NAVIGATION  ------------------
        # Scheduling: when dt has passed or restart:
        if self.t0fms+self.dtfms<simt or simt<self.t0fms:
            self.t0fms = simt
            
            # FMS LNAV mode:
            qdr, dist = qdrdist(self.lat, self.lon, self.actwplat, self.actwplon) #[deg][nm])
           
            
            # Check whether shift based dist [nm] is required, set closer than WP turn distance
            iwpclose = np.where(self.swlnav*(dist < self.actwpturn))[0] ## NOte --->> maybe hardcoden
            
            iwpclose = np.where(self.swlnav*(dist < 10))[0] ## NOte --->> maybe hardcoden
                        

            # Shift waypoints for aircraft i where necessary
            for i in iwpclose:

                # Get next wp (lnavon = False if no more waypoints)
                lat, lon, alt, spd, xtoalt, toalt, lnavon, flyby =  \
                       self.route[i].getnextwp()  # note: xtoalt,toalt in [m]

                # End of route/no more waypoints: switch off LNAV
                if not lnavon:
                    self.swlnav[i] = False # Drop LNAV at end of route

                # In case of no LNAV, do not allow VNAV mode on it sown
                if not self.swlnav[i]:
                    self.swvnav[i] = False
                    
                self.actwplat[i]   = lat
                self.actwplon[i]   = lon
                self.actwpflyby[i] = int(flyby) # 1.0 in case of fly by, els fly over

                # User entered altitude

                if alt >= 0.:
                    self.actwpalt[i] = alt
                    
                # VNAV=-ALT mode
                # calculated altitude is available and active
                if toalt  >= 0. and self.swvnav[i]: # somewhere there is an altitude constraint ahead

                    # Descent VNAV mode (T/D logic)
                    if self.alt[i] > toalt+10.*ft:       

                        #Steepness dh/dx in [m/m], for now 1:3 rule of thumb
                        steepness = 3000.*ft/(10.*nm)
                        
                        #Calculate max allowed altitude at next wp (above toalt)
                        self.actwpalt[i] = toalt + xtoalt*steepness

                        # Dist to waypoint where descent should start
                        self.dist2vs[i] = (self.alt[i]-self.actwpalt[i])/steepness
 
                        # Flat earth distance to next wp
                        dy = (lat-self.lat[i])
                        dx = (lon-self.lon[i])*self.coslat[i]
                        legdist = 60.*nm*sqrt(dx*dx+dy*dy)


                        #If descent is urgent, descent with maximum steepness
                        if legdist < self.dist2vs[i]:
                            self.aalt[i] = self.actwpalt[i] # dial in altitude of next waypoint as calculated

                            t2go         = max(0.1,legdist)/max(0.01,self.gs[i])
                            self.actwpvs[i]  = (self.actwpalt[i] - self.alt[i])/t2go
                                              
                        else: 

                            # normal case: still time till descent starts
                       
                            # Calculate V/s using steepness, 
                            # protect against zero/invalid ground speed value
                            self.actwpvs[i] = -steepness*(self.gs[i] +   \
                                            (self.gs[i]<0.2*self.tas[i])*self.tas[i])

                    # Climb VNAV mode: climb as soon as possible (T/C logic)                        
                    elif self.swvnav[i] and self.alt[i]<toalt-10.*ft:

                        self.actwpalt[i] = toalt
                        self.aalt[i]     = self.actwpalt[i] # dial in altitude of next waypoint as calculated
                        self.dist2vs[i]  = 9999.

                    # Level leg: never start V/S
                    else:
                        self.dist2vs[i] = -999.
                        
                #No altirude defined: never start V/S
                else:
                    self.dist2vs[i] = -999.
               
                # VNAV spd mode: use speed of this waypoint as commaded speed
                # while passing waypoint and save next speed for passing next wp
                if self.swvnav[i] and self.actwpspd[i]>0.0: # check mode and value

                    # Select CAS or Mach command by checking value of actwpspd
                    if self.actwpspd[i]<2.0: # Mach command

                       self.aspd[i] = mach2cas(self.actwpspd[i],self.alt[i])
                       self.ama[i]  = self.actwpspd[i]                            

                    else:    # CAS command
                       self.aspd[i] = self.actwpspd[i]
                       self.ama[i]  = cas2tas(spd,self.alt[i])
                    
                
                if spd>0. and self.swlnav[i] and self.swvnav[i]: # Valid speed and LNAV and VNAV ap modes are on
                   self.actwpspd[i] = spd                           
                else:
                   self.actwpspd[i] = -999.

                # Calculate distance before waypoint where to start the turn
                # Turn radius:      R = V2 tan phi / g
                # Distance to turn: wpturn = R * tan (1/2 delhdg) but max 4 times radius
                # using default bank angle per flight phase
                turnrad = self.tas[i]*self.tas[i]/tan(self.bank[i]) /g0 /nm # [nm] 

                dy = (self.actwplat[i]-self.lat[i])
                dx = (self.actwplon[i]-self.lon[i])*self.coslat[i]
                qdr[i] = degrees(atan2(dx,dy))                    

                self.actwpturn[i] = self.actwpflyby[i]*                     \
                     max(10.,abs(turnrad*tan(radians(0.5*degto180(qdr[i]-    \
                     self.route[i].wpdirfrom[self.route[i].iactwp])))))  # [nm]                

            # End of Waypoint switching loop
            
            # Do VNAV start of descent check
            dy = (self.actwplat-self.lat)
            dx = (self.actwplon-self.lon)*self.coslat
            dist2wp = 60.*nm*np.sqrt(dx*dx+dy*dy)
            steepness = 3000.*ft/(10.*nm)

            # VNAV AP LOGIC
            self.swvnavvs = self.swlnav*self.swvnav*((dist2wp<self.dist2vs) + \
                                     (self.actwpalt>self.alt))            

            self.avs = (1-self.swvnavvs)*self.avs + self.swvnavvs*steepness*self.gs
            self.aalt = (1-self.swvnavvs)*self.aalt + self.swvnavvs*self.actwpalt

            # Set headings based on swlnav
            self.ahdg = np.where(self.swlnav, qdr, self.ahdg)

        #-------------END of FMS update -------------------
      
        # NOISE: Turbulence
        if self.turbulence:
            timescale=np.sqrt(simdt)
            trkrad=np.radians(self.trk)
            
            #write turbulences in array
            turb=np.array(self.standardturbulence)
            turb=np.where(turb>1e-6,turb,1e-6)
            
            #horizontal flight direction
            turbhf=np.random.normal(0,turb[0]*timescale,self.ntraf) #[m]
            
            #horizontal wing direction
            turbhw=np.random.normal(0,turb[1]*timescale,self.ntraf) #[m]
            
            #vertical direction
            turbalt=np.random.normal(0,turb[2]*timescale,self.ntraf) #[m]
            
            #latitudinal, longitudinal direction
            turblat=np.cos(trkrad)*turbhf-np.sin(trkrad)*turbhw #[m]
            turblon=np.sin(trkrad)*turbhf+np.cos(trkrad)*turbhw #[m]

        else:
            turbalt=np.zeros(self.ntraf) #[m]
            turblat=np.zeros(self.ntraf) #[m]
            turblon=np.zeros(self.ntraf) #[m]


        # ASAS AP switches

        #--------- Input to Autopilot settings to follow: destination or ASAS ----------
        #import pdb
        #pdb.set_trace()
        # desired autopilot settings due to ASAS
        self.deshdg = self.asasactive*self.asashdg + (1-self.asasactive)*self.ahdg
        self.desspd = self.asasactive*self.asasspd + (1-self.asasactive)*self.aptas
        self.desalt = self.asasactive*self.asasalt + (1-self.asasactive)*self.aalt
        self.desvs  = self.asasactive*self.asasvsp + (1-self.asasactive)*self.avs
        
        # check for the flight envelope
        self.perf.limits()

        # Update autopilot settings with values within the flight envelope

        # Autopilot selected speed setting [m/s]
        # To do: add const Mach const CAS mode
        self.desspd = ((self.desspd<vcas2tas(self.lspd,self.alt)) + ( self.lspd == 0.0 ))*self.desspd + (self.desspd>vcas2tas(self.lspd,self.alt))*vcas2tas(self.lspd,self.alt)


        # Autopilot selected altitude [m]
        self.desalt = (self.lalt ==0)*self.desalt + (self.lalt!=0)*self.lalt

        # Autopilot selected heading
        self.deshdg = self.deshdg

        # Autopilot selected vertical speed (V/S)
        self.desvs = (self.lvs==0)*self.desvs + (self.lvs!=0)*self.lvs

        # below crossover altitude: CAS=const, above crossover altitude: MA = const
        #climb/descend above crossover: Ma = const, else CAS = const  
        #ama is fixed when above crossover
        check = self.abco*(self.ama == 0.)
        swma = np.where(check==True)
        self.ama[swma] = vcas2mach(self.desspd[swma], self.alt[swma])

        # ama is deleted when below crossover
        check2 = self.belco*(self.ama!=0.)
        swma2 = np.where(check2==True)
        self.ama[swma2] = 0. 

        #---------- Basic Autopilot  modes ----------

        # SPD HOLD/SEL mode: aspd = autopilot selected speed (first only eas)
        # for information:    

# no more ?       self.aptas = (self.actwpspd > 0.01)*self.actwpspd*self.swvnav + \
#                            np.logical_or((self.actwpspd <= 0.01),np.logical_not (self.swvnav))*self.aptas

        self.delspd = self.desspd - self.tas
        swspdsel = np.abs(self.delspd) > 0.4  # <1 kts = 0.514444 m/s
        ax = np.minimum(abs(self.delspd / max(1e-8,simdt)), self.ax)

        self.tas = swspdsel * (self.tas + ax * np.sign(self.delspd) *  \
                                          simdt) + (1. - swspdsel) * self.tas

        # Speed conversions
        self.cas = vtas2cas(self.tas, self.alt)
        self.gs  = self.tas
        self.M   = vtas2mach(self.tas, self.alt)

        # Update performance every self.perfdt seconds
        if abs(simt - self.perft0) >= self.perfdt:               
            self.perft0 = simt            
            self.perf.perf()

        # update altitude
        self.eps = np.array(self.ntraf * [0.01])  # almost zero for misc purposes
        swaltsel = np.abs(self.desalt-self.alt) >      \
                  np.maximum(3.,np.abs(2. * simdt * np.abs(self.vs))) # 3.[m] = 10 [ft] eps alt

        self.vs = swaltsel*np.sign(self.desalt-self.alt)*       \
                    ( (1-self.swvnav)*np.abs(1500./60.*ft) +    \
                      self.swvnav*np.abs(self.desvs)         )

        self.alt = swaltsel * (self.alt + self.vs * simdt) +   \
                   (1. - swaltsel) * self.desalt + turbalt

        # HDG HOLD/SEL mode: ahdg = ap selected heading
        delhdg = (self.deshdg - self.trk + 180.) % 360 - 180.  # [deg]

        # omega = np.degrees(g0 * np.tan(self.aphi) / \
        # np.maximum(self.tas, self.eps))

        # nominal bank angles per phase from BADA 3.12
        omega = np.degrees(g0 * np.tan(self.bank) / \
                           np.maximum(self.tas, self.eps))

        self.hdgsel = np.abs(delhdg) > np.abs(2. * simdt * omega)

        self.trk = (self.trk + simdt * omega * self.hdgsel * np.sign(delhdg)) % 360.

        #--------- Kinematics: update lat,lon,alt ----------
        ds = simdt * self.gs

        self.lat = self.lat + np.degrees(ds * np.cos(np.radians(self.trk)+turblat) \
                                         / Rearth)

        self.coslat = np.cos(np.deg2rad(self.lat))

        self.lon = self.lon + np.degrees(ds * np.sin(np.radians(self.trk)+turblon) \
                                         / self.coslat / Rearth)

        # Update trails when switched on
        if self.swtrails:
            self.trails.update(simt, self.lat, self.lon,
                               self.lastlat, self.lastlon,
                               self.lasttim, self.id, self.trailcol)
        else:
            self.lastlat = self.lat
            self.lastlon = self.lon
            self.lattime = simt
            
        # ----------------Logger----------------
        #Thom flight statistics:
        self.distance_2D    = self.distance_2D + simdt * self.gs # [m]
        self.distance_3D    = self.distance_3D + simdt * np.sqrt(self.gs**2 + self.vs**2) # [m]
        self.flightime      = self.flightime + simdt # [sec]
        self.work           = self.work + self.perf.Thr * simdt * self.tas # [work] 
        #End Flight Statistics
        
        #Start flight statistics logger
        if simt >= self.ExperimentStart and simt <= self.ExperimentEnd \
        and(self.FlstSwitch)and((self.Flstt0+self.Flstdt)<simt):
            self.Flstt0=simt
            
            condition1 = np.where(np.array(kwikdist(self.DeleteCenterLatLon[0],self.DeleteCenterLatLon[1],self.lat,self.lon) )[0] <= self.ExperimentRadius )[0]
            condition2=np.where(self.createtime >= self.ExperimentStart)    # Check Created after experiment time
            condition3=np.where(self.createtime <= self.ExperimentEnd)      # Check created before experiment end
            conditions=np.intersect1d(condition1,condition2) #check common values for conditions (in area) and created after experiment starttime
            conditions=np.intersect1d(conditions,condition3) #check for third   
            
            for i in range(self.ntraf):
                if i in conditions:             # check with conditions
                                                
                    # Temp ReWrite test
                    writedlines = self.log.writetxt(simt,'%s,%s,%s,%s,%s,%s,%s,%s' % \
                                               (simt,self.id[i],self.type[i],self.createtime[i], self.distance_2D[i],\
                                               self.distance_3D[i], self.flightime[i], self.work[i]\
                                                )) #Return distance in NM
                    self.log.buffer_Flst.append(writedlines)  
        #end flight statistics logger
        
        
        
        #Start Snap logger
        if simt >= self.ExperimentStart and simt <= self.ExperimentEnd \
        and(self.SnapSwitch)and((self.Snapt0+self.Snapdt)<simt):
            self.Snapt0=simt
            # Check if Createtime is right and is inside (circular) area
            
            condition1 = np.where(np.array(kwikdist(self.DeleteCenterLatLon[0],self.DeleteCenterLatLon[1],self.lat,self.lon) )[0] <= self.ExperimentRadius)[0]
            condition2=np.where(self.createtime >= self.ExperimentStart)    # Check Created after experiment time
            condition3=np.where(self.createtime <= self.ExperimentEnd)      # Check created before experiment end
            conditions=np.intersect1d(condition1,condition2) #check common values for conditions (in area) and created after experiment starttime
            conditions=np.intersect1d(conditions,condition3) #check for third

            
            
            for i in range(self.ntraf):
                if i in conditions:             # check with conditions
                    
                    writedlines = self.log.writetxt(simt,'%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s' % \
                                               (simt,self.id[i],self.type[i],self.createtime[i], \
                                                self.lat[i],self.lon[i],self.alt[i], \
                                                self.tas[i],self.gs[i],self.vs[i],self.cas[i], self.trk[i], \
                                                self.adsb.recepProbInterf_db[i],np.mean(self.adsb.recepProbRange_db[i][:]),np.mean( self.adsb.recepProb_DB[i])\
                                                ))
                                                
                   
                    self.log.buffer_Snap.append(writedlines)  
                                        
                                        
                                        
            
        else:
            pass     
        #End Snap logger
        
        #Start TMX logger
        if self.TmxSwitch: # No switch for if aircraft is in area (maybe do with specific flight time???)
            if self.Tmxt0+self.Tmxdt<simt or simt<self.Tmxt0:
                self.Tmxt0 = simt
                
                writedlines = self.log.writetxt(simt,'%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s' % \
                               (simt,self.ntraf,len(self.dbconf.conflist_now),len(self.dbconf.LOSlist_now),\
                               np.mean(self.adsb.recepProbInterf_db),np.mean(self.adsb.recepProbRange_db),np.mean( self.adsb.recepProb_DB),\
                               np.count_nonzero(self.ACInArea), (self.ntraf-np.count_nonzero(self.ACInArea)), len(self.dbconf.conflist_exp),len(self.dbconf2.conflist_exp), \
                               len(self.dbconf.conflist_all),len(self.dbconf2.conflist_all)\
                               ))
                self.log.buffer_Tmx.append(writedlines)
        #end TMX logger
          
          
        #Global variables switch
        if self.GlobSwitch and simt>=30 and self.GlobSwitch2:
            
            
            writedlines = self.log.writetxt(simt,'%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s' % \
                               (simt,self.log.ScenName,\
                               self.adsb.sigma_lat,self.adsb.sigma_lon,\
                               self.adsb.R0,self.adsb.AdsbMessageTime,self.adsb.update_rate,\
                               self.ExperimentStart,self.ExperimentEnd,self.ExperimentRadius,\
                               self.DeleteDistance,self.DeleteSwitch\
                               ))
            
            self.log.buffer_Glob.append(writedlines)
            self.GlobSwitch2=False

            
       
        #Write Logfiles
        if self.t0writelog+self.dtwritelog<simt or simt<self.t0writelog:
            self.t0writelog = simt
            if self.TmxSwitch:     #Only if Snap is enabled
                self.log.savetxt(0) # Zie hierboven (real locations)
                self.log.buffer_Tmx=[] # and clear buffer
            if self.SnapSwitch:     #Only if Snap is enabled
                self.log.savetxt(1) 
                self.log.buffer_Snap=[] # and clear buffer
            if self.ConfSwitch:     #Only if Conf is enabled
                #pdb.set_trace()
                self.log.savetxt(2) # 
                self.log.buffer_Conf=[] # and clear buffer
            if self.IntSwitch:     #Only if xx is enabled
                #pdb.set_trace()
                self.log.savetxt(3) # Intrusion
                self.log.buffer_Int=[] # and clear buffer
            if self.FlstSwitch:
                self.log.savetxt(4) #flight statistiocs
                self.log.buffer_Flst=[]
            if self.GlobSwitch and simt >= 35:
                self.log.savetxt(5) #flight statistiocs
                #pdb.set_trace()
                self.GlobSwitch = False #Log only once all global variables
                

            self.lasttim[:] = simt


        # ----------------AREA check----------------
        # Circular Area check
        if self.DeleteSwitch == True and simt >= 3 and self.ntraf != 0\
        and (self.t0Delete+self.dtDelete<simt or simt<self.t0Delete):
            
            self.t0Delete=simt
            self.DistanceList= kwikdist(self.DeleteCenterLatLon[0],self.DeleteCenterLatLon[1],self.lat[:],self.lon[:])
            OutRegionList = np.asarray( (self.DistanceList[:] >= self.DeleteDistance) )[0] # Reshape
            self.DeleteIdx=np.where(OutRegionList)[0]
            
            DeleteId=np.array([])
            
            if np.size(self.DeleteIdx) != 0: #check if not empty
                for i in self.DeleteIdx: #Create vectors with IDs to be deleted
                    
                    DeleteId=np.append(DeleteId,self.id[i])
            
                for i in range(np.size(DeleteId)): #Delete IDs in DeleteId
                    
                    if (self.createtime[self.id2idx(DeleteId[i])] + 600) <= simt: # + 10 min
                        #pdb.set_trace()
                        self.delete(DeleteId[i])
                    else:
                        pass
            else:
                pass
        # End Circular Area Check
                
        #Ad data if AC is in area: ACInArea
        
        
        AreaDistanceList= kwikdist(self.DeleteCenterLatLon[0],self.DeleteCenterLatLon[1],self.lat[:],self.lon[:])
        OutAreaList = np.where( np.asarray(AreaDistanceList[:] >= self.ExperimentRadius )[0])[0] # Reshape
        InAreaList = np.where( np.asarray(AreaDistanceList[:] < self.ExperimentRadius )[0])[0] # Reshape
        
        self.ACInArea[OutAreaList] = False
        self.ACInArea[InAreaList] = True
        
                
        # AcInRange
            
            
        # Update area once per areadt seconds:
        if self.swarea and abs(simt - self.areat0) > self.areadt:
            # Update loop timer
            self.areat0 = simt
            # Check all aircraft
            i = 0
            while (i < self.ntraf):
                # Current status
                if self.area == "Square":
                    inside = self.arealat0 <= self.lat[i] <= self.arealat1 and \
                             self.arealon0 <= self.lon[i] <= self.arealon1 and \
                             self.alt[i] >= self.areafloor and \
                             (self.alt[i] >= 1500 or self.swtaxi)

                elif self.area == "Circle":

                    # delete aircraft if it is too far from the center of the circular area, or if has decended below the minimum altitude
                    distance = kwikdist(self.arealat0, self.arealon0, self.lat[i], self.lon[i])  # [NM]
                    inside = distance < self.arearadius and self.alt[i] >= self.areafloor

                # Compare with previous: when leaving area: delete command
                if self.inside[i] and not inside:
                    self.delete(self.id[i])

                else:
                    # Update area status
                    self.inside[i] = inside
                    i = i + 1

        return

    def id2idx(self, acid):
        """Find index of aircraft id"""
        try:
            return self.id.index(acid.upper())
        except:
            return -1

    def changeTrailColor(self, color, idx):
        """Change color of aircraft trail"""
        self.trailcol[idx] = self.trails.colorList[color]
        return

    def setNoise(self, A):
        """Noise (turbulence, ADBS-transmission noise, ADSB-truncated effect)"""
        self.noise              = A
        self.trunctime          = 1                   # seconds
        self.transerror         = [1, 100, 100 * ft]  # [degree,m,m] standard bearing, distance, altitude error
        self.standardturbulence = [0, 0.1, 0.1]       # m/s standard turbulence  (nonnegative)
        # in (horizontal flight direction, horizontal wing direction, vertical)

        self.turbulence     = self.noise
        self.ADSBtransnoise = self.noise
        self.ADSBtrunc      = self.noise

    def engchange(self, acid, engid):
        """Change of engines"""
        self.perf.engchange(acid, engid)
        return

    def selhdg(self, idx, hdg):  # HDG command
        """ Select heading command: HDG acid, hdg """
        if idx < 0:
            return False  # Aircraft not found

        # Give autopilot commands
        self.ahdg[idx]   = float(hdg)
        self.swlnav[idx] = False
        # Everything went ok!
        return True

    def selspd(self, idx, spd):  # SPD command
        """ Select speed command: SPD acid, spd (= CASkts/Mach) """
        if idx < 0:
            return False  # Aircraft not found

        # When >=2.0 it is probably CASkts else it is Mach
        if spd >= 2.0:
            self.aspd[idx] = spd * kts  # CAS m/s
            self.ama[idx]  = cas2mach(spd*kts, self.alt[idx])
        else:
            self.aspd[idx] = mach2cas(spd) # Convert Mach to CAS m/s
            self.ama[idx]  = spd
        # Switch off VNAV: SPD command overrides
        self.swvnav[idx] = False

        return True
