/***********************************************************************/
/** capture_mod: the session script for The Witcher 3 (adapters/witcher3 in the capture_mod
/** repository). Installed by `capture install witcher3` as a loose script mod:
/**   <game>\mods\modCaptureMod\content\scripts\local\capture_mod.ws
/**
/** WitcherScript cannot read or write files, so the exchange differs from the other games:
/**   in:   console commands, pasted into the debug console by adapters/witcher3/session.py
/**   out:  [CaptureMod] lines in Documents\The Witcher 3\scriptslog.txt (game started with
/**         -debugscripts), read by the same module
/** Every command takes a sequence number first. Its answer is any number of data lines
/** "d|<seq>|...", one state line "s|<seq>|key=value ..." and a last line "e|<seq>|ok|..." or
/** "e|<seq>|error|...". Nothing is kept between commands: the Python side holds the session's
/** state and passes back what a command needs.
/***********************************************************************/

function CmB( b : bool ) : string { if ( b ) return "1"; return "0"; }
function CmF( f : float, prec : int ) : string { return FloatToStringPrec( f, prec ); }
function CmV( v : Vector ) : string { return CmF( v.X, 4 ) + "," + CmF( v.Y, 4 ) + "," + CmF( v.Z, 4 ); }
function CmV6( v : Vector ) : string { return CmF( v.X, 6 ) + "," + CmF( v.Y, 6 ) + "," + CmF( v.Z, 6 ); }
function CmLine( s : string ) { LogChannel( 'CaptureMod', s ); }

function CmInGame() : bool
{
	if ( !theGame.IsActive() ) return false;
	if ( !thePlayer ) return false;
	if ( !theGame.GetWorld() ) return false;
	return true;
}

function CmStateText() : string
{
	var d : CCameraDirector;
	var base, rel : float;
	if ( !CmInGame() ) return "ingame=0";
	d = theGame.GetWorld().GetCameraDirector();
	// engine time as a whole number of seconds plus a remainder under 16 s, so that the remainder
	// keeps microseconds (one float holds about 2 ms at 20,000 s)
	base = FloorF( theGame.GetEngineTimeAsSeconds() / 16.0 ) * 16.0;
	rel = EngineTimeToFloat( theGame.GetEngineTime() - EngineTimeFromFloat( base ) );
	return "ingame=1"
		+ " pm=" + CmB( theGame.GetPhotomodeEnabled() )
		+ " pcam=" + CmB( CmCamIsOn() )
		+ " paused=" + CmB( theGame.IsPaused() )
		+ " held=" + CmB( theGame.IsPausedForReason( "CaptureMod" ) )
		+ " scale=" + CmF( theGame.GetTimeScale(), 6 )
		+ " engine_base=" + CmF( base, 0 )
		+ " engine_rel=" + CmF( rel, 7 )
		+ " gt=" + GameTimeToSeconds( theGame.GetGameTime() )
		+ " hpm=" + CmF( theGame.GetHoursPerMinute(), 6 )
		+ " cam=" + CmV( d.GetCameraPosition() )
		+ " fwd=" + CmV6( d.GetCameraForward() )
		+ " up=" + CmV6( d.GetCameraUp() )
		+ " fov=" + CmF( d.GetFov(), 4 )
		+ " player=" + CmV( thePlayer.GetWorldPosition() )
		+ " heading=" + CmF( thePlayer.GetHeading(), 4 )
		+ " weather=" + NameToString( GetWeatherConditionName() )
		+ " menu=" + CmB( theGame.GetGuiManager().IsAnyMenu() )
		+ " streaming=" + CmB( theGame.IsStreaming() )
		+ " black=" + CmB( theGame.IsBlackscreen() || theGame.IsFading() )
		+ " dialog=" + CmB( theGame.IsDialogOrCutscenePlaying() )
		+ " area=" + NameToString( theGame.GetCommonMapManager().GetCurrentArea() )
		+ " ms=" + theGame.GetLocalTimeAsMilliseconds()
		+ " savelock=" + CmB( theGame.AreSavesLocked() )
		+ " input=" + NameToString( theInput.GetContext() )
		+ " world=" + theGame.GetWorld().GetDepotPath();
}

function CmOk( seq : int, optional text : string )
{
	CmLine( "s|" + seq + "|" + CmStateText() );
	CmLine( "e|" + seq + "|ok|" + text );
}

function CmError( seq : int, text : string )
{
	CmLine( "s|" + seq + "|" + CmStateText() );
	CmLine( "e|" + seq + "|error|" + text );
}

// true (after answering with an error) when a command that needs a loaded world has none
function CmNoWorld( seq : int ) : bool
{
	if ( CmInGame() ) return false;
	CmLine( "e|" + seq + "|error|no world is loaded" );
	return true;
}

// the next number of an underscore-separated list ("1.5_-2_3"), taken off its front
function CmNext( out rest : string ) : float
{
	var left, right : string;
	if ( StrSplitFirst( rest, "_", left, right ) )
	{
		rest = right;
		return StringToFloat( left, 0 );
	}
	left = rest;
	rest = "";
	return StringToFloat( left, 0 );
}

// ---------------------------------------------------------------------------------------------

exec function cm_hello( seq : int )
{
	CmLine( "s|" + seq + "|" + CmStateText() );
	CmLine( "e|" + seq + "|ok|capture_mod 1" );
}

exec function cm_state( seq : int ) { CmOk( seq ); }

exec function cm_echo( seq : int, text : string )
{
	CmLine( "d|" + seq + "|" + StrLen( text ) + "|" + text );
	CmLine( "e|" + seq + "|ok|" );
}

// The HUD, the tutorial hints and the player (with the horse it rides), shown or hidden.
exec function cm_hud( seq : int, on : int )
{
	var hud : CR4ScriptedHud;
	if ( CmNoWorld( seq ) ) return;
	hud = (CR4ScriptedHud)theGame.GetHud();
	if ( hud ) hud.ForceShow( on == 1, HVS_User );
	theGame.GetGuiManager().HideTutorial( on != 1, true );
	CmOk( seq );
}

// hidden 1: the player, his horse and what he rides out of the picture; 0: back. His items
// (swords, crossbow, bolts: 11 item entities) go with his body: hiding them as well changed 0.002%
// of the pixels of a close view (probes/hide_probe.py, 2026-11-23).
exec function cm_hide( seq : int, hidden : int )
{
	var vehicle : CGameplayEntity;
	var horse : CNewNPC;
	if ( CmNoWorld( seq ) ) return;
	thePlayer.SetVisibility( hidden == 0 );
	vehicle = thePlayer.GetUsedVehicle();
	if ( vehicle ) vehicle.SetHideInGame( hidden != 0, true );
	horse = thePlayer.GetHorseWithInventory();
	if ( horse ) horse.SetVisibility( hidden == 0 );
	CmOk( seq );
}

// The player out of the scene for a take: hidden, out of other characters' sight and targeting
// (gameplay visibility) and of their way (character collisions off: people pass through him), with
// the horse he rides the same, so over time steps people neither see, avoid nor bump into him
// (capture_mod AGENTS.md: "The player does not exist for the scene"). Takes park him where he
// stands. The game puts a teleported player on the ground whatever his physics (gravity off, and
// physical movement off, both left him on the ground), with all his collisions off he falls
// through it (a loading screen that never ended), and parked 80 m away he takes the crowd with him
// (people within 15 m of the spot: 59 to 7 in a few seconds; 2026-11-23). Saving is locked while
// he is parked. cm_unpark puts him back at the given point.
// The horse (or what else) the player rides: out of people's sight and way, or back.
function CmGhostMount( ghost : bool )
{
	var mount : CActor;
	mount = (CActor)thePlayer.GetUsedVehicle();
	if ( !mount ) return;
	mount.SetGameplayVisibility( !ghost );
	mount.EnableCharacterCollisions( !ghost );
}

exec function cm_park( seq : int, x : float, y : float, z : float )
{
	var lock : int;
	if ( CmNoWorld( seq ) ) return;
	theGame.CreateNoSaveLock( "CaptureModPark", lock, true, false );
	thePlayer.SetVisibility( false );
	thePlayer.SetGameplayVisibility( false );
	thePlayer.EnableCharacterCollisions( false );
	CmGhostMount( true );
	thePlayer.TeleportWithRotation( Vector( x, y, z ), thePlayer.GetWorldRotation() );
	CmOk( seq );
}

exec function cm_unpark( seq : int, x : float, y : float, z : float, yaw : float )
{
	if ( CmNoWorld( seq ) ) return;
	thePlayer.EnableCharacterCollisions( true );
	thePlayer.SetGameplayVisibility( true );
	CmGhostMount( false );
	thePlayer.TeleportWithRotation( Vector( x, y, z ), EulerAngles( 0, yaw, 0 ) );
	theGame.ReleaseNoSaveLockByName( "CaptureModPark" );
	CmOk( seq );
}

// The game's photo mode on and off: probe tools only since 2026-11-23 (takes hold the world with
// our pause and the photo mode's camera alone, cm_freeze). Water is not updated while paused (the
// game's own photo mode keeps it moving, which a held instant must not). The wind in trees, grass
// and clouds follows engine time, so its clocks (cm_wind) are left at the game's own 1.
function CmPhotoOn()
{
	var cam, top : CCustomCamera;
	if ( theGame.GetPhotomodeEnabled() ) return;
	top = theGame.GetWorld().GetCameraDirector().GetTopmostCamera();
	theGame.SetPhotomodeEnabled( true );
	cam = theGame.GetPhotomodeCamera();
	cam.Activate();
	cam.SetCameraWorldPosition( top.GetCameraWorldPosition() + top.GetCameraWorldOffset() );
	cam.SetCameraWorldRotation( top.GetCameraWorldRotation() );
	cam.SetNoclip( true );
	cam.UpdateWithoutInput( true );
	theGame.SetPhotomodeCameraCanMove( false );
	theGame.PauseGameplayFx( true );
	theGame.GetWorld().ForceUpdateWaterOnPause( false );
}

function CmPhotoOff()
{
	if ( !theGame.GetPhotomodeEnabled() ) return;
	theGame.SetPhotomodeEnabled( false );
	theGame.PauseGameplayFx( false );
	theGame.GetWorld().ForceUpdateWaterOnPause( false );
	theGame.GetGameCamera().Activate( 0.0, false );
}

// The photo mode's camera as the rendered camera, without the photo mode itself (which resets
// people's poses and cloth whenever it is switched off and on in a held world: probes/
// cloth_step_probe.py, 2026-11-23). Placed where the game's camera is; cm_pose then places it.
function CmCamOn()
{
	var cam, top : CCustomCamera;
	cam = theGame.GetPhotomodeCamera();
	top = theGame.GetWorld().GetCameraDirector().GetTopmostCamera();
	if ( top == cam ) return;
	cam.Activate();
	cam.SetCameraWorldPosition( top.GetCameraWorldPosition() + top.GetCameraWorldOffset() );
	cam.SetCameraWorldRotation( top.GetCameraWorldRotation() );
	cam.SetNoclip( true );
	cam.UpdateWithoutInput( true );
}

function CmCamOff()
{
	if ( theGame.GetWorld().GetCameraDirector().GetTopmostCamera() == theGame.GetPhotomodeCamera() )
		theGame.GetGameCamera().Activate( 0.0, false );
}

function CmCamIsOn() : bool
{
	return theGame.GetWorld().GetCameraDirector().GetTopmostCamera() == theGame.GetPhotomodeCamera();
}

// Holds the world: our pause, the photo mode's camera (CmCamOn), the weather's own changes paused,
// the game's keys taken away (so that a key typed into the game by mistake opens no menu).
exec function cm_freeze( seq : int )
{
	if ( CmNoWorld( seq ) ) return;
	SetWindSpeedTreeTimeScale( 1 );
	SetWindCloudsTimeScale( 1 );
	RequestWeatherPause( true );
	if ( theInput.GetContext() != 'EMPTY_CONTEXT' ) theInput.StoreContext( 'EMPTY_CONTEXT' );
	CmPhotoOff();
	if ( !theGame.IsPausedForReason( "CaptureMod" ) ) theGame.Pause( "CaptureMod" );
	CmCamOn();
	CmOk( seq );
}

// Probe tools: the photo mode alone on or off (the pause untouched), and the game's free camera.
exec function cm_photo( seq : int, on : int )
{
	if ( CmNoWorld( seq ) ) return;
	if ( on == 1 ) CmPhotoOn(); else CmPhotoOff();
	CmOk( seq );
}

exec function cm_freecam( seq : int, on : int, x : float, y : float, z : float, pitch : float, yaw : float )
{
	if ( CmNoWorld( seq ) ) return;
	theGame.EnableFreeCamera( on == 1 );
	if ( on == 1 ) theGame.MoveFreeCamera( Vector( x, y, z ), EulerAngles( pitch, yaw, 0 ) );
	CmLine( "d|" + seq + "|enabled=" + CmB( theGame.IsFreeCameraEnabled() ) + " at=" + CmV( theGame.GetFreeCameraPosition() ) );
	CmOk( seq );
}

// The photo mode's camera made the rendered camera without the photo mode itself (1), or the
// game's camera again (0).
exec function cm_pcam( seq : int, on : int )
{
	if ( CmNoWorld( seq ) ) return;
	if ( on == 1 ) CmCamOn(); else CmCamOff();
	CmOk( seq );
}

// The game's own camera (not the photo mode's) at a world pose: the same class, so the same calls.
exec function cm_gpose( seq : int, x : float, y : float, z : float, pitch : float, yaw : float, fov : float, tilt : float )
{
	var cam : CCustomCamera;
	if ( CmNoWorld( seq ) ) return;
	cam = theGame.GetGameCamera();
	cam.SetNoclip( true );
	cam.SetCameraWorldPosition( Vector( x, y, z ) );
	cam.SetCameraWorldRotation( EulerAngles( pitch, yaw, 0 ) );
	if ( fov > 0 ) cam.SetFov( fov );
	cam.SetTilt( tilt );
	cam.UpdateWithoutInput( true );
	CmLine( "d|" + seq + "|pos=" + CmV( cam.GetCameraWorldPosition() ) + " offset=" + CmV( cam.GetCameraWorldOffset() ) );
	CmOk( seq );
}

exec function cm_unfreeze( seq : int )
{
	if ( CmNoWorld( seq ) ) return;
	SetWindSpeedTreeTimeScale( 1 );
	SetWindCloudsTimeScale( 1 );
	RequestWeatherPause( false );
	if ( theInput.GetContext() == 'EMPTY_CONTEXT' ) theInput.RestoreContext( 'EMPTY_CONTEXT', true );
	if ( theGame.IsPausedForReason( "CaptureMod" ) ) theGame.Unpause( "CaptureMod" );
	theGame.RemoveTimeScale( 'CaptureModStep' );
	CmPhotoOff();
	CmCamOff();
	CmOk( seq );
}

// The photo-mode camera at a world pose. fov <= 0 leaves the field of view as it is.
exec function cm_pose( seq : int, x : float, y : float, z : float, pitch : float, yaw : float, roll : float, optional fov : float )
{
	var cam : CCustomCamera;
	if ( CmNoWorld( seq ) ) return;
	cam = theGame.GetPhotomodeCamera();
	cam.SetCameraWorldPosition( Vector( x, y, z ) );
	cam.SetCameraWorldRotation( EulerAngles( pitch, yaw, roll ) );
	if ( fov > 0 ) cam.SetFov( fov );
	cam.UpdateWithoutInput( true );
	CmOk( seq );
}

exec function cm_tilt( seq : int, v : float )
{
	if ( CmNoWorld( seq ) ) return;
	theGame.GetPhotomodeCamera().SetTilt( v );
	theGame.GetPhotomodeCamera().UpdateWithoutInput( true );
	CmOk( seq );
}

// The photo mode's own tick: engine time, wind and grass move by exactly dt on the next frame while
// the pause stays on, but people do not (they animate where they stand). A probe's tool; takes
// use cm_stepw.
exec function cm_step( seq : int, dt : float )
{
	if ( CmNoWorld( seq ) ) return;
	theGame.GetPhotomodeEffects().SetPhotomodeTickTime( dt );
	CmOk( seq );
}

// The clocks of the wind in trees and of the clouds, as multiples of engine time: 1 is the game's
// own, 0 holds them through time steps as well (measured 2026-11-23: with 0, thirty steps of
// 1/30 s moved the grass but neither trees nor clouds). A probe's tool; captures leave them at 1.
exec function cm_wind( seq : int, trees : float, clouds : float )
{
	var a, b : bool;
	if ( CmNoWorld( seq ) ) return;
	a = SetWindSpeedTreeTimeScale( trees );
	b = SetWindCloudsTimeScale( clouds );
	CmOk( seq, "trees=" + CmB( a ) + " clouds=" + CmB( b ) );
}

// Whether water keeps being updated while the game is paused (the game's photo mode turns it on).
exec function cm_water( seq : int, on : int )
{
	if ( CmNoWorld( seq ) ) return;
	theGame.GetWorld().ForceUpdateWaterOnPause( on == 1 );
	CmOk( seq );
}

// Our pause alone, on or off: off with photo mode on gives the photo-mode camera a running world
// (scouting previews, and probes that need the world to move).
exec function cm_pause( seq : int, on : int )
{
	if ( CmNoWorld( seq ) ) return;
	if ( on == 1 && !theGame.IsPausedForReason( "CaptureMod" ) ) theGame.Pause( "CaptureMod" );
	if ( on != 1 && theGame.IsPausedForReason( "CaptureMod" ) ) theGame.Unpause( "CaptureMod" );
	CmOk( seq );
}

// No saving (the player's quick save, autosaves) while a session moves the player about.
exec function cm_savelock( seq : int, on : int )
{
	var lock : int;
	if ( CmNoWorld( seq ) ) return;
	if ( on == 1 ) theGame.CreateNoSaveLock( "CaptureMod", lock, true, false );
	else theGame.ReleaseNoSaveLockByName( "CaptureMod" );
	CmOk( seq );
}

// A time step that moves the whole world: our pause off, the world run at a time scale set every
// frame, held again when the step is done. The photo mode's tick (cm_step) advances the clock, wind
// and grass but not people (57 people at Hierarch Square did not move over 30 steps of 1/30 s,
// probes/people_step_probe.py, 2026-11-23), so it is not used. Takes use cm_stepe: every frame of
// the step covers the same game time. cm_stepw (a probe's tool now) covers a quarter of what is
// left each frame and lands exactly, but its frames shrink to microseconds at the end and the next
// step starts at milliseconds, a jump in time step that the cloth solver turns into a kick at
// every step (an awning moved 9-12 levels of 255 per 1/30 s step and growing, 2-3 with even steps,
// probes/cloth_rate_probe.py, 2026-11-23). The per-frame hook is the game's own CR4Game.OnTick,
// wrapped. The command answers at once ("started"); the hook logs "t|<seq>|advanced=...
// frames=..." when the step is done.
@addField(CR4Game) var cmStepActive : bool;
@addField(CR4Game) var cmStepSeq : int;
@addField(CR4Game) var cmStepStart : EngineTime;
@addField(CR4Game) var cmStepLength : float;
@addField(CR4Game) var cmStepScale : float;
@addField(CR4Game) var cmStepDone : float;
@addField(CR4Game) var cmStepFrames : int;
@addField(CR4Game) var cmStepPhoto : bool;
@addField(CR4Game) var cmStepFrac : float;
@addField(CR4Game) var cmStepPaused : bool;
@addField(CR4Game) var cmStepSoft : int;
@addField(CR4Game) var cmStepSoftScale : float;

@wrapMethod(CR4Game) function OnTick()
{
	wrappedMethod();
	if ( cmStepActive ) CmStepTick();
}

@addField(CR4Game) var cmStepEven : int;
@addField(CR4Game) var cmStepRan : int;
@addField(CR4Game) var cmStepFrameReal : float;

@addMethod(CR4Game) function CmStepEnd( done : float )
{
	cmStepActive = false;
	if ( cmStepPaused ) Pause( "CaptureMod" );
	RemoveTimeScale( 'CaptureModStep' );
	if ( cmStepPhoto ) CmPhotoOn();
	CmLine( "t|" + cmStepSeq + "|advanced=" + CmF( done, 7 ) + " frames=" + cmStepFrames + " ran=" + cmStepRan
		+ " frame_s=" + CmF( cmStepFrameReal, 5 ) );
}

// Even steps: every frame of the step covers the same game time (what is left over the frames
// left), so the cloth's solver sees no jump in its time step; the step lands within a share of
// one frame's time instead of exactly.
@addMethod(CR4Game) function CmStepEvenTick( done : float, left : float )
{
	var ran, scale : float;
	var framesLeft : int;
	ran = done - cmStepDone;
	if ( ran > 0.0000001 )
	{
		cmStepRan += 1;
		cmStepFrameReal = 0.5 * cmStepFrameReal + 0.5 * ( ran / cmStepScale );
		cmStepDone = done;
	}
	framesLeft = cmStepEven - cmStepRan;
	if ( left <= 0.000003 || cmStepFrames > 600 || ( framesLeft <= 0 && left < 0.2 * cmStepLength / cmStepEven ) )
	{
		CmStepEnd( done );
		return;
	}
	if ( framesLeft < 1 ) framesLeft = 1;
	scale = left / framesLeft / cmStepFrameReal;
	if ( scale > 1.0 ) scale = 1.0;
	if ( scale < 0.000001 ) scale = 0.000001;
	cmStepScale = scale;
	SetTimeScale( scale, 'CaptureModStep', 2000, false, true );
}

@addMethod(CR4Game) function CmStepTick()
{
	var done, left, frameReal, scale : float;
	done = EngineTimeToFloat( GetEngineTime() - cmStepStart );
	left = cmStepLength - done;
	cmStepFrames += 1;
	if ( cmStepEven > 0 )
	{
		CmStepEvenTick( done, left );
		return;
	}
	if ( left <= 0.000003 || cmStepFrames > 600 )
	{
		CmStepEnd( done );
		return;
	}
	frameReal = ( done - cmStepDone ) / cmStepScale;     // real seconds the last frame took
	cmStepDone = done;
	if ( frameReal <= 0.0001 ) frameReal = 1.0 / 60.0;
	if ( cmStepSoft > 0 )                                  // the first frames at a small scale (a probe's option)
	{
		cmStepSoft -= 1;
		cmStepScale = cmStepSoftScale;
		SetTimeScale( cmStepScale, 'CaptureModStep', 2000, false, true );
		return;
	}
	scale = left * cmStepFrac / frameReal;
	if ( scale > 1.0 ) scale = 1.0;
	if ( scale < 0.000001 ) scale = 0.000001;
	cmStepScale = scale;
	SetTimeScale( scale, 'CaptureModStep', 2000, false, true );
}

@addMethod(CR4Game) function CmStepBegin( seq : int, dt : float, keepPhoto : bool, frac : float, soft : float )
{
	var scale : float;
	cmStepFrac = frac;
	if ( cmStepFrac <= 0 ) cmStepFrac = 0.25;
	if ( cmStepFrac > 0.95 ) cmStepFrac = 0.95;
	cmStepSeq = seq;
	cmStepStart = GetEngineTime();
	cmStepLength = dt;
	cmStepDone = 0;
	cmStepFrames = 0;
	cmStepPhoto = GetPhotomodeEnabled() && !keepPhoto;
	cmStepPaused = IsPausedForReason( "CaptureMod" );     // held by a time scale instead: left so
	scale = dt * cmStepFrac * 60.0;                        // the first frame: frac of dt at 60 frames/s
	if ( scale > 1.0 ) scale = 1.0;
	cmStepSoft = 0;
	if ( soft > 0 )
	{
		cmStepSoft = 3;
		cmStepSoftScale = soft;
		scale = soft;
	}
	cmStepEven = 0;
	cmStepRan = 0;
	cmStepScale = scale;
	SetTimeScale( scale, 'CaptureModStep', 2000, false, true );
	cmStepActive = true;
}

@addMethod(CR4Game) function CmStepEvenBegin( n : int, frameReal : float )
{
	var scale : float;
	cmStepEven = n;
	cmStepFrameReal = frameReal;
	scale = cmStepLength / n / frameReal;
	if ( scale > 1.0 ) scale = 1.0;
	cmStepScale = scale;
	SetTimeScale( scale, 'CaptureModStep', 2000, false, true );
}

// An even step (see CmStepEvenTick) over n frames; frameReal: the real time of one frame as the
// caller measured it (the first frame's scale comes from it).
exec function cm_stepe( seq : int, dt : float, n : int, frameReal : float, optional keep : int )
{
	var frames : int;
	var frame : float;
	if ( CmNoWorld( seq ) ) return;
	frames = n;
	if ( frames < 1 ) frames = 1;
	frame = frameReal;
	if ( frame <= 0.001 ) frame = 1.0 / 60.0;
	theGame.CmStepBegin( seq, dt, keep == 1, 0.25, 0 );
	theGame.CmStepEvenBegin( frames, frame );
	if ( keep != 1 ) CmPhotoOff();
	if ( theGame.IsPausedForReason( "CaptureMod" ) ) theGame.Unpause( "CaptureMod" );
	CmOk( seq, "started" );
}

// The photo mode holds people in place even with the world running (57 people, at most 3.8 cm
// over 1 s of steps with it on; up to 1.67 m with it off, as in play; 2026-11-23), so if it is on
// it is switched off for the step and on again after (keep 1: left as it is). A probe's tool.
exec function cm_stepw( seq : int, dt : float, optional keep : int, optional frac : float, optional soft : float )
{
	if ( CmNoWorld( seq ) ) return;
	theGame.CmStepBegin( seq, dt, keep == 1, frac, soft );
	if ( keep != 1 ) CmPhotoOff();                       // keep 1: the photo mode left as it is
	if ( theGame.IsPausedForReason( "CaptureMod" ) ) theGame.Unpause( "CaptureMod" );
	CmOk( seq, "started" );
}

// People followed by handle (a probe's tool): cm_watch keeps the living people within r of a point,
// cm_watched says where each is now ("i x y z yaw", or "i gone"). Finding the same person again by
// position from outside picked someone standing nearby too often (2026-11-23).
@addField(CR4Game) var cmWatched : array< CNewNPC >;

@addMethod(CR4Game) function CmWatch( p : Vector, r : float ) : int
{
	var ents : array< CGameplayEntity >;
	var npc : CNewNPC;
	var i : int;
	cmWatched.Clear();
	FindGameplayEntitiesInSphere( ents, p, r, 200 );
	for ( i = 0; i < ents.Size(); i += 1 )
	{
		npc = (CNewNPC)ents[ i ];
		if ( npc && npc.IsAlive() && npc != thePlayer.GetHorseWithInventory() ) cmWatched.PushBack( npc );
	}
	return cmWatched.Size();
}

@addMethod(CR4Game) function CmWatchedLines( seq : int )
{
	var i : int;
	for ( i = 0; i < cmWatched.Size(); i += 1 )
	{
		if ( cmWatched[ i ] ) CmLine( "d|" + seq + "|" + i + " " + CmV( cmWatched[ i ].GetWorldPosition() ) + " " + CmF( cmWatched[ i ].GetHeading(), 1 ) );
		else CmLine( "d|" + seq + "|" + i + " gone" );
	}
}

exec function cm_watch( seq : int, x : float, y : float, z : float, r : float )
{
	var n : int;
	if ( CmNoWorld( seq ) ) return;
	n = theGame.CmWatch( Vector( x, y, z ), r );
	theGame.CmWatchedLines( seq );
	CmOk( seq, "watched=" + n );
}

exec function cm_watched( seq : int )
{
	if ( CmNoWorld( seq ) ) return;
	theGame.CmWatchedLines( seq );
	CmOk( seq );
}

// The wind at a point, as the game's physics and its visuals have it (a probe's tool).
exec function cm_windat( seq : int, x : float, y : float, z : float )
{
	if ( CmNoWorld( seq ) ) return;
	CmLine( "d|" + seq + "|wind=" + CmV( theGame.GetWindAtPoint( Vector( x, y, z ) ) )
		+ " visual=" + CmV( theGame.GetWindAtPointForVisuals( Vector( x, y, z ) ) ) );
	CmOk( seq );
}

exec function cm_cloth( seq : int, t : float )
{
	if ( CmNoWorld( seq ) ) return;
	theGame.GetPhotomodeEffects().SetPhotomodeClothsSimulationTime( t );
	CmOk( seq );
}

exec function cm_timescale( seq : int, s : float )
{
	if ( CmNoWorld( seq ) ) return;
	if ( s < 0 ) theGame.RemoveTimeScale( 'CaptureMod' );
	else theGame.SetTimeScale( s, 'CaptureMod', 1000, false, true );
	CmOk( seq );
}

exec function cm_teleport( seq : int, x : float, y : float, z : float, yaw : float )
{
	if ( CmNoWorld( seq ) ) return;
	thePlayer.TeleportWithRotation( Vector( x, y, z ), EulerAngles( 0, yaw, 0 ) );
	CmOk( seq );
}

exec function cm_ground( seq : int, x : float, y : float, z : float )
{
	var gz : float;
	var ok : bool;
	var p : Vector;
	if ( CmNoWorld( seq ) ) return;
	p = Vector( x, y, z );
	ok = theGame.GetWorld().PhysicsCorrectZ( p, gz );
	CmLine( "d|" + seq + "|ok=" + CmB( ok ) + " z=" + CmF( gz, 4 ) + " water=" + CmF( theGame.GetWorld().GetWaterLevel( p, true ), 4 ) );
	CmOk( seq );
}

// Another world of the game, as its own gotoNovigrad and the like do but without their autosave:
// novigrad (Velen and Novigrad), skellige, kaer_morhen, prolog_village (White Orchard),
// wyzima_castle, bob (Toussaint). With a position the player lands there, otherwise where the
// world starts. A loading screen follows; the state's "world" and "streaming" say when it is over.
exec function cm_world( seq : int, key : name, optional x : float, optional y : float, optional z : float, optional yaw : float )
{
	var path : string;
	if ( CmNoWorld( seq ) ) return;
	switch ( key )
	{
		case 'novigrad':        path = "levels\novigrad\novigrad.w2w"; break;
		case 'skellige':        path = "levels\skellige\skellige.w2w"; break;
		case 'kaer_morhen':     path = "levels\kaer_morhen\kaer_morhen.w2w"; break;
		case 'prolog_village':  path = "levels\prolog_village\prolog_village.w2w"; break;
		case 'wyzima_castle':   path = "levels\wyzima_castle\wyzima_castle.w2w"; break;
		case 'bob':             path = "dlc\bob\data\levels\bob\bob.w2w"; break;
		default:
			CmError( seq, "no world named " + NameToString( key ) );
			return;
	}
	if ( x == 0 && y == 0 && z == 0 ) theGame.ScheduleWorldChangeToMapPin( path, '' );
	else theGame.ScheduleWorldChangeToPosition( path, Vector( x, y, z ), EulerAngles( 0, yaw, 0 ) );
	CmLine( "e|" + seq + "|ok|" + path );
}

// The map's places in the loaded world: with all = 0 only the ones a player can travel to (road
// signs, harbours), which have a spot to stand on; one data line each, the title last.
exec function cm_pins( seq : int, optional all : int )
{
	var pins : array< SEntityMapPinInfo >;
	var i, n : int;
	var travel : bool;
	if ( CmNoWorld( seq ) ) return;
	pins = theGame.GetCommonMapManager().GetEntityMapPins( theGame.GetWorld().GetDepotPath() );
	for ( i = 0; i < pins.Size(); i += 1 )
	{
		travel = pins[i].entityType == 'RoadSign' || pins[i].entityType == 'Harbor';
		if ( all != 1 && !travel ) continue;
		n += 1;
		CmLine( "d|" + seq + "|name=" + NameToString( pins[i].entityName ) + " type=" + NameToString( pins[i].entityType )
			+ " pos=" + CmV( pins[i].entityPosition ) + " land=" + CmV( pins[i].fastTravelTeleportWayPointPosition )
			+ " yaw=" + CmF( pins[i].fastTravelTeleportWayPointRotation.Yaw, 2 )
			+ " title=" + GetLocStringByKeyExt( StrLower( "map_location_" + NameToString( pins[i].entityName ) ) ) );
	}
	CmOk( seq, "n=" + n + " of " + pins.Size() );
}

// The named place nearest to a point (road signs and harbours carry the names a player knows).
exec function cm_place( seq : int, x : float, y : float, z : float )
{
	var pins : array< SEntityMapPinInfo >;
	var i, best : int;
	var d, bestD : float;
	var p : Vector;
	if ( CmNoWorld( seq ) ) return;
	p = Vector( x, y, z );
	pins = theGame.GetCommonMapManager().GetEntityMapPins( theGame.GetWorld().GetDepotPath() );
	best = -1;
	for ( i = 0; i < pins.Size(); i += 1 )
	{
		if ( pins[i].entityType != 'RoadSign' && pins[i].entityType != 'Harbor' ) continue;
		d = VecDistance2D( p, pins[i].entityPosition );
		if ( best < 0 || d < bestD ) { best = i; bestD = d; }
	}
	if ( best >= 0 )
		CmLine( "d|" + seq + "|name=" + NameToString( pins[best].entityName ) + " distance=" + CmF( bestD, 1 )
			+ " title=" + GetLocStringByKeyExt( StrLower( "map_location_" + NameToString( pins[best].entityName ) ) ) );
	CmOk( seq );
}

// Time of day: the clock set to h:m, and how many game hours pass per real minute (0 holds it).
exec function cm_clock( seq : int, h : int, m : int )
{
	if ( CmNoWorld( seq ) ) return;
	theGame.SetGameTime( GameTimeCreate( GameTimeDays( theGame.GetGameTime() ), h, m, 0 ), true );
	CmOk( seq );
}

exec function cm_clockrate( seq : int, hoursPerMinute : float )
{
	if ( CmNoWorld( seq ) ) return;
	theGame.SetHoursPerMinute( hoursPerMinute );
	CmOk( seq );
}

exec function cm_weather( seq : int, w : name, optional blend : float )
{
	var ok : bool;
	if ( CmNoWorld( seq ) ) return;
	ok = RequestWeatherChangeTo( w, blend, false );
	if ( ok ) CmOk( seq ); else CmError( seq, "the game refused weather " + NameToString( w ) );
}

// Line probes against the static scene. rays: x1_y1_z1_x2_y2_z2 repeated, underscores between
// all numbers. One data line holds every answer: h_x_y_z_nx_ny_nz per ray, joined by "/".
exec function cm_rays( seq : int, rays : string )
{
	var a, b, pos, normal : Vector;
	var res, rest : string;
	var n : int;
	var hit : bool;
	var world : CWorld;
	if ( CmNoWorld( seq ) ) return;
	world = theGame.GetWorld();
	rest = rays;
	n = 0;
	while ( StrLen( rest ) > 0 )
	{
		a.X = CmNext( rest ); a.Y = CmNext( rest ); a.Z = CmNext( rest );
		b.X = CmNext( rest ); b.Y = CmNext( rest ); b.Z = CmNext( rest );
		hit = world.StaticTrace( a, b, pos, normal );
		if ( n > 0 ) res += "/";
		if ( hit ) res += "1_" + CmF( pos.X, 3 ) + "_" + CmF( pos.Y, 3 ) + "_" + CmF( pos.Z, 3 ) + "_" + CmF( normal.X, 3 ) + "_" + CmF( normal.Y, 3 ) + "_" + CmF( normal.Z, 3 );
		else res += "0";
		n += 1;
	}
	CmLine( "d|" + seq + "|" + n + "|" + res );
	CmLine( "e|" + seq + "|ok|" );
}

// People, animals and vehicles around a point: one data line each.
exec function cm_ents( seq : int, x : float, y : float, z : float, radius : float )
{
	var ents : array< CGameplayEntity >;
	var i : int;
	var a : CActor;
	var npc : CNewNPC;
	var mac : CMovingPhysicalAgentComponent;
	var kind, extra : string;
	var horse : CNewNPC;
	if ( CmNoWorld( seq ) ) return;
	FindGameplayEntitiesInSphere( ents, Vector( x, y, z ), radius, 1000 );
	horse = thePlayer.GetHorseWithInventory();
	for ( i = 0; i < ents.Size(); i += 1 )
	{
		a = (CActor)ents[i];
		npc = (CNewNPC)ents[i];
		if ( ents[i] == thePlayer ) kind = "player";
		else if ( npc && npc == horse ) kind = "playerhorse";
		else if ( npc ) kind = "npc";
		else if ( a ) kind = "actor";
		else continue;      // containers, doors, signs and other things that do not move
		extra = "";
		if ( a )
		{
			mac = (CMovingPhysicalAgentComponent)a.GetMovingAgentComponent();
			if ( mac ) extra = " r=" + CmF( mac.GetCapsuleRadius(), 3 ) + " h=" + CmF( mac.GetCapsuleHeight(), 3 );
			extra += " alive=" + CmB( a.IsAlive() );
		}
		if ( npc ) extra += " human=" + CmB( npc.IsHuman() ) + " animal=" + CmB( npc.IsAnimal() ) + " horse=" + CmB( npc.IsHorse() ) + " monster=" + CmB( npc.IsMonster() );
		CmLine( "d|" + seq + "|kind=" + kind + " pos=" + CmV( ents[i].GetWorldPosition() ) + " yaw=" + CmF( ents[i].GetHeading(), 2 ) + extra
			+ " tags=" + ents[i].GetTagsString() + " name=" + ents[i].GetName() );
	}
	CmOk( seq, "n=" + ents.Size() );
}

// Deletes the moving things at the given points (x_y_z repeated; the positions cm_ents gave):
// the nearest NPC within 0.5 m of each, never the player or the player's horse.
// The entities of what a person holds or wears as items (a torch, a spear, a basket) hidden: they
// are entities of their own and can stay behind, floating, when the person goes. Answers how many.
function CmHideNpcItems( npc : CNewNPC ) : int
{
	var items : array< SItemUniqueId >;
	var inv : CInventoryComponent;
	var ent : CItemEntity;
	var i, n : int;
	inv = npc.GetInventory();
	if ( !inv ) return 0;
	inv.GetAllItems( items );
	for ( i = 0; i < items.Size(); i += 1 )
	{
		ent = inv.GetItemEntityUnsafe( items[ i ] );
		if ( ent )
		{
			ent.SetHideInGame( true, true );
			n += 1;
		}
	}
	return n;
}

// Removes the person (not the player's horse) nearest each of the given points, within 0.5 m, and
// hides the entities of their items first. keep 1 (a probe's): leaves the items as they are.
exec function cm_remove( seq : int, points : string, optional keep : int )
{
	var ents : array< CGameplayEntity >;
	var rest : string;
	var p : Vector;
	var i, removed, asked, items : int;
	var npc : CNewNPC;
	var horse : CNewNPC;
	if ( CmNoWorld( seq ) ) return;
	horse = thePlayer.GetHorseWithInventory();
	rest = points;
	while ( StrLen( rest ) > 0 )
	{
		p.X = CmNext( rest ); p.Y = CmNext( rest ); p.Z = CmNext( rest );
		asked += 1;
		ents.Clear();
		FindGameplayEntitiesInSphere( ents, p, 0.5, 10 );
		for ( i = 0; i < ents.Size(); i += 1 )
		{
			npc = (CNewNPC)ents[i];
			if ( npc && npc != horse )
			{
				if ( keep != 1 ) items += CmHideNpcItems( npc );
				npc.Destroy();
				removed += 1;
				break;
			}
		}
	}
	CmOk( seq, "asked=" + asked + " removed=" + removed + " items=" + items );
}

// ---------------------------------------------------------------------------------------------
// Getting into a world from the main menu, and saving (adapters/witcher3/launch.py).

// What the main menu's Continue does: load the most recent save.
exec function cm_continue( seq : int )
{
	if ( CmInGame() )
	{
		CmOk( seq, "already in a world" );
		return;
	}
	theGame.LoadLastGameInit();
	CmLine( "e|" + seq + "|ok|loading the last save" );
}

// What New Game > Blood and Wine only does: a ready character in the open world (Velen), with
// no prologue to play through. For a machine that has no save yet.
exec function cm_newgame( seq : int )
{
	var result : ELoadGameResult;
	if ( CmInGame() )
	{
		CmOk( seq, "already in a world" );
		return;
	}
	TutorialMessagesEnable( false );
	result = theGame.InitStandaloneDLCLoading( 'bob_000_000', 0 );
	theGame.EnableUberMovement( true );
	CmLine( "e|" + seq + "|ok|starting a Blood and Wine only game, result " + result );
}

exec function cm_save( seq : int )
{
	if ( CmNoWorld( seq ) ) return;
	theGame.SaveGame( SGT_QuickSave, -1 );
	CmOk( seq, "quick save requested" );
}

// ---------------------------------------------------------------------------------------------
// Probes and picture controls.

// Where world points fall in the picture the game renders now: x_y_z repeated in, one data line
// out with ok_x_y per point joined by "/" (x, y as the game's view ratios).
exec function cm_project( seq : int, points : string )
{
	var d : CCameraDirector;
	var rest, res : string;
	var p : Vector;
	var x, y : float;
	var ok : bool;
	var n : int;
	if ( CmNoWorld( seq ) ) return;
	d = theGame.GetWorld().GetCameraDirector();
	rest = points;
	while ( StrLen( rest ) > 0 )
	{
		p.X = CmNext( rest ); p.Y = CmNext( rest ); p.Z = CmNext( rest );
		ok = d.WorldVectorToViewRatio( p, x, y );
		if ( n > 0 ) res += "/";
		res += CmB( ok ) + "_" + CmF( x, 6 ) + "_" + CmF( y, 6 );
		n += 1;
	}
	CmLine( "d|" + seq + "|" + n + "|" + res );
	CmOk( seq );
}

// The photo mode's picture controls: switched on they replace the game's own exposure and grade
// with fixed values (exposure in stops around 0), and lens effects can be set to nothing.
exec function cm_fx( seq : int, on : int )
{
	if ( CmNoWorld( seq ) ) return;
	theGame.GetPhotomodeEffects().SetEnabled( on == 1 );
	CmOk( seq );
}

exec function cm_exposure( seq : int, v : float )
{
	var fx : CR4PhotomodeEffects;
	if ( CmNoWorld( seq ) ) return;
	fx = theGame.GetPhotomodeEffects();
	fx.SetExposure( v );
	CmOk( seq, "exposure=" + CmF( fx.GetExposure(), 4 ) + " contrast=" + CmF( fx.GetContrast(), 4 ) + " saturation=" + CmF( fx.GetSaturation(), 4 )
		+ " vignette=" + CmF( fx.GetVignette(), 4 ) + " grain=" + CmF( fx.GetFilmGrain(), 4 ) + " ca=" + CmF( fx.GetChromaticAberration(), 4 ) );
}

// The hour the sky and the light are drawn for, held whatever the game clock does (hour < 0: free).
exec function cm_envtime( seq : int, hour : float )
{
	if ( CmNoWorld( seq ) ) return;
	if ( hour < 0 ) DisableFakeEnvTime(); else ForceFakeEnvTime( hour );
	CmOk( seq );
}
