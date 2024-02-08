# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""cros_test_sharding recipe module

Provides optimization algorithm for distributing tests among shards
"""
import math
from typing import List
from itertools import filterfalse
from recipe_engine import recipe_api


class TestCase:
  """Test information

  Model for test information, enriched with average execution time.
  """

  def __init__(self, test):
    """Populate test Model information

    Args:
      test: test_case.proto:TestCase
    """
    self.test = test
    self.name = test.id.value
    # Change to
    self.execution_time = self.test_times.get(_get_test_sub_name(self.name), 1)

  # Average test times.  Are generated from resultdb
  test_times = {
      'tast.a11y.LiveCaption': 29,
      'tast.a11y.Smoke': 7,
      'tast.apps.LaunchCanvas': 14,
      'tast.apps.LaunchSystemWebAppsFromURL': 18,
      'tast.apps.Sharesheet': 20,
      'tast.arc.ADBValidity': 3,
      'tast.arc.AudioValidity': 8,
      'tast.arc.Boot': 32,
      'tast.arc.BuildProperties': 12,
      'tast.arc.CPUSet': 33,
      'tast.arc.ChromeCrash': 37,
      'tast.arc.DownloadManager': 4,
      'tast.arc.Drivefs': 83,
      'tast.arc.Gamepad': 6,
      'tast.arc.IMEBlockingVK': 5,
      'tast.arc.IntentForward': 2,
      'tast.arc.LaunchIntent': 4,
      'tast.arc.MIDIClient': 2,
      'tast.arc.ManagedBoot': 97,
      'tast.arc.ManagedPlayStoreIcon': 40,
      'tast.arc.ManagedProvisioning': 83,
      'tast.arc.MultiNetworking': 62,
      'tast.arc.Notification': 9,
      'tast.arc.Optin': 67,
      'tast.arc.OptinNetworkError': 124,
      'tast.arc.RemovableMedia': 20,
      'tast.arc.SettingsBridge': 5,
      'tast.arc.StandardizedKeyboardKeys': 54,
      'tast.arc.StandardizedKeyboardTyping': 16,
      'tast.arc.StandardizedMouseHover': 24,
      'tast.arc.StandardizedMouseLeftClick': 18,
      'tast.arc.StandardizedMouseRightClick': 18,
      'tast.arc.StandardizedMouseScroll': 50,
      'tast.arc.StartStop': 37,
      'tast.arc.UreadaheadGuestCompat': 6,
      'tast.arc.WindowState': 18,
      'tast.assistant.Hotkey': 7,
      'tast.assistant.StartupInSignedOutMode': 13,
      'tast.assistant.VolumeQueries': 10,
      'tast.audio.ALSAConformance': 46,
      'tast.audio.AloopLoadedFixture': 3,
      'tast.audio.CheckingAudioFormats': 55,
      'tast.audio.CrasBench': 20,
      'tast.audio.CrasDLCManager': 8,
      'tast.audio.CrasFeatures': 7,
      'tast.audio.CrasNoiseCancellation': 27,
      'tast.audio.CrasPlay': 5,
      'tast.audio.CrasRecord': 5,
      'tast.audio.CrasRecordQuality': 6,
      'tast.audio.CrasSpeakOnMuteDetection': 10,
      'tast.audio.CrasSpeakOnMuteDetectionTransitions': 13,
      'tast.audio.CrasStreamMix': 20,
      'tast.audio.DBusStreamCounts': 11,
      'tast.audio.FileOwnershipMigration': 28,
      'tast.audio.FloopBasic': 20,
      'tast.audio.Microphone': 10,
      'tast.audio.PlaybackAudioControls': 53,
      'tast.audio.UIInput': 84,
      'tast.bruschetta.AppEmacs': 12,
      'tast.bruschetta.AppEmacsWindowOperations': 11,
      'tast.bruschetta.AppVscodeWindowOperations': 16,
      'tast.bruschetta.CommandVim': 9,
      'tast.bruschetta.CopyFilesToGuest': 12,
      'tast.bruschetta.CopyPaste': 3,
      'tast.bruschetta.HomeDirectoryShare': 19,
      'tast.bruschetta.LaunchBrowser': 5,
      'tast.bruschetta.ShareDownloads': 16,
      'tast.bruschetta.Toolkit': 5,
      'tast.camera.CCAAPI': 12,
      'tast.camera.CCAQRCode': 11,
      'tast.camera.CCAUILauncher': 9,
      'tast.camera.CCAUISmoke': 8,
      'tast.camera.EncodeAccelJPEG': 2,
      'tast.crash.Ephemeral': 7,
      'tast.crash.Histograms': 13,
      'tast.crash.KernelIwlwifiError': 31,
      'tast.crash.Sender': 5,
      'tast.crash.SenderRateLimit': 3,
      'tast.crash.ServiceFailure': 4,
      'tast.crash.SuspendFailure': 32,
      'tast.crash.User': 2,
      'tast.critical-android-shard-0': 526,
      'tast.critical-android-shard-1': 595,
      'tast.critical-android-shard-2': 677,
      'tast.critical-chrome-shard-0': 2583,
      'tast.critical-chrome-shard-1': 791,
      'tast.critical-chrome-shard-2': 2373,
      'tast.critical-crostini-shard-0': 397,
      'tast.critical-crostini-shard-1': 1043,
      'tast.critical-crostini-shard-2': 1860,
      'tast.critical-crostini-shard-3': 1687,
      'tast.critical-crostini-shard-4': 1525,
      'tast.critical-crostini-shard-5': 930,
      'tast.critical-system-shard-0': 893,
      'tast.critical-system-shard-1': 1228,
      'tast.critical-system-shard-2': 724,
      'tast.crostini.AudioBasic': 11,
      'tast.crostini.AudioPlaybackConfigurations': 111,
      'tast.crostini.Basic': 2,
      'tast.crostini.BasicLxdNext': 2,
      'tast.crostini.Chrony': 2,
      'tast.crostini.CommandCd': 10,
      'tast.crostini.CommandPs': 6,
      'tast.crostini.CommandVim': 10,
      'tast.crostini.CopyFilesToLinuxFiles': 13,
      'tast.crostini.CopyPaste': 4,
      'tast.crostini.CrashReporter': 2,
      'tast.crostini.DebianUpgradeAlert': 43,
      'tast.crostini.DisplayDensity': 5,
      'tast.crostini.DragDrop': 21,
      'tast.crostini.FilesAppWatch': 5,
      'tast.crostini.GPUEnabled': 2,
      'tast.crostini.HomeDirectoryShare': 20,
      'tast.crostini.LaunchBrowser': 8,
      'tast.crostini.LaunchTerminal': 2,
      'tast.crostini.Launcher': 15,
      'tast.crostini.NestedVM': 2,
      'tast.crostini.NoAccessToDownloads': 2,
      'tast.crostini.NoAccessToDrive': 6,
      'tast.crostini.NoSharedFolder': 8,
      'tast.crostini.Notify': 2,
      'tast.crostini.OOMEvent': 38,
      'tast.crostini.OpenWithTerminal': 11,
      'tast.crostini.PackageInfo': 2,
      'tast.crostini.PackageInstallUninstall': 4,
      'tast.crostini.RemoveCancel': 10,
      'tast.crostini.RemoveOk': 15,
      'tast.crostini.ResizeCancel': 9,
      'tast.crostini.ResizeOk': 18,
      'tast.crostini.ResizeRestart': 41,
      'tast.crostini.ResizeSpaceConstrained': 33,
      'tast.crostini.Restart': 48,
      'tast.crostini.RestartIcon': 27,
      'tast.crostini.RunWithARC': 3,
      'tast.crostini.SSHFSMount': 2,
      'tast.crostini.SecureCopyPaste': 34,
      'tast.crostini.ShareDownloads': 23,
      'tast.crostini.ShareDownloadsAddFiles': 21,
      'tast.crostini.ShareDrive': 29,
      'tast.crostini.ShareFilesCancel': 17,
      'tast.crostini.ShareFilesManage': 23,
      'tast.crostini.ShareFilesOK': 24,
      'tast.crostini.ShareFilesRestart': 54,
      'tast.crostini.ShareFilesToast': 30,
      'tast.crostini.ShareFolderZipFile': 29,
      'tast.crostini.ShareFolders': 28,
      'tast.crostini.ShareInvalidPaths': 2,
      'tast.crostini.ShareMovies': 64,
      'tast.crostini.SharedFontFiles': 2,
      'tast.crostini.Snapshot': 18,
      'tast.crostini.SyncTime': 2,
      'tast.crostini.TaskManager': 4,
      'tast.crostini.Toolkit': 7,
      'tast.crostini.UninstallInvalidApp': 2,
      'tast.crostini.VerifyAppWayland': 4,
      'tast.crostini.VerifyAppX11': 2,
      'tast.crostini.VmcExtraDisk': 7,
      'tast.crostini.VmcStart': 7,
      'tast.crostini.Webserver': 3,
      'tast.crostini.Xattrs': 2,
      'tast.cryptohome.AddRemoveFactorsEphemeral': 10,
      'tast.cryptohome.AddRemovePIN': 10,
      'tast.cryptohome.AuthSessionUnlock': 8,
      'tast.cryptohome.AuthSessionUnlockEphemeral': 8,
      'tast.cryptohome.FileStability': 26,
      'tast.cryptohome.FscryptEncryptionPolicy': 4,
      'tast.cryptohome.GuestAuthSession': 10,
      'tast.cryptohome.KioskEphemeralMount': 10,
      'tast.cryptohome.LegacyLabelAuthSession': 10,
      'tast.cryptohome.RecoveryCrypto': 3,
      'tast.cryptohome.USSMigrationPinAfterPasswordMigration': 22,
      'tast.cryptohome.UpdatePassword': 12,
      'tast.cryptohome.UpdatePin': 8,
      'tast.cryptohome.UpdateRecovery': 11,
      'tast.cryptohome.UssMigrationChallengeCredential': 8,
      'tast.cryptohome.UssMigrationPasswordPin': 28,
      'tast.cryptohome.UssMigrationPinPassword': 24,
      'tast.debugd.CoreScheduler': 5,
      'tast.debugd.DRMTraceTool': 26,
      'tast.dlp.DataLeakPreventionRulesListClipboard': 16,
      'tast.dlp.DataLeakPreventionRulesListClipboardExt': 18,
      'tast.dlp.DataLeakPreventionRulesListDragdrop': 35,
      'tast.dlp.DataLeakPreventionRulesListFilesUSB': 28,
      'tast.dlp.DataLeakPreventionRulesListPrinting': 16,
      'tast.dlp.DataLeakPreventionRulesListScreenshareEntireScreen': 30,
      'tast.dlp.DataLeakPreventionRulesListScreenshareTab': 114,
      'tast.dlp.DataLeakPreventionRulesListScreenshareWindow': 114,
      'tast.dlp.DataLeakPreventionRulesListScreenshot': 24,
      'tast.documentscanapi.Scan': 18,
      'tast.example.ChromeExtension': 12,
      'tast.example.DBus': 2,
      'tast.factory.Goofy': 14,
      'tast.factory.Toolkit': 3,
      'tast.featured.FeatureLibraryLateBoot': 2,
      'tast.featured.LatePlatformFeatures': 24,
      'tast.filemanager.Deletion': 44,
      'tast.filemanager.DrivefsUI': 3,
      'tast.filemanager.Fusebox': 12,
      'tast.filemanager.RecentFilesAppear': 15,
      'tast.filemanager.ZipMount': 156,
      'tast.graphics.Clvk': 2,
      'tast.graphics.DEQP': 7,
      'tast.graphics.DRM': 8,
      'tast.graphics.FPS': 17,
      'tast.graphics.KernelMemory': 6,
      'tast.graphics.KmsvncConnect': 5,
      'tast.graphics.ScreenshotCLI': 6,
      'tast.health.DiagnosticsPass': 3,
      'tast.health.DiagnosticsPassV2': 5,
      'tast.health.DiagnosticsRun': 4,
      'tast.health.MonitorBluetoothEvent': 11,
      'tast.health.MonitorEventStartup': 3,
      'tast.health.MonitorThunderboltEvent': 10,
      'tast.health.MonitorUnuploadedCrashEvent': 41,
      'tast.health.MonitorUploadedCrashEvent': 11,
      'tast.health.MonitorUsbEvent': 11,
      'tast.health.ProbeBootPerformanceInfo': 6,
      'tast.health.ProbeSensorInfo': 5,
      'tast.health.RunVolumeButtonRoutine': 6,
      'tast.hwsec.AccountDiskUsage': 16,
      'tast.hwsec.ChapsAttributePolicy': 22,
      'tast.hwsec.ChapsECDSA': 13,
      'tast.hwsec.ChapsPKCS1V15': 33,
      'tast.hwsec.ChapsRSAPSS': 46,
      'tast.hwsec.CryptohomeBadPerms': 3,
      'tast.hwsec.CryptohomeNonDirs': 5,
      'tast.hwsec.DaemonsRestartStress': 22,
      'tast.hwsec.Login': 17,
      'tast.hwsec.LoginGuest': 9,
      'tast.hwsec.UnmountAll': 12,
      'tast.kernel.PerfCallgraph': 2,
      'tast.lacros.Activate': 32,
      'tast.lacros.AppLauncherLaunch': 11,
      'tast.lacros.AudioPinnedStream': 8,
      'tast.lacros.AudioPlay': 26,
      'tast.lacros.AudioRecord': 27,
      'tast.lacros.Basic': 12,
      'tast.lacros.Guest': 19,
      'tast.lacros.ShelfLaunch': 6,
      'tast.lacros.URLRedirect': 60,
      'tast.lockscreen.CloseLid': 14,
      'tast.lockscreen.KeyboardShortcut': 18,
      'tast.lockscreen.ShowPassword': 24,
      'tast.login.AuthError': 26,
      'tast.login.ChangePassword': 71,
      'tast.login.Chrome': 14,
      'tast.login.ChromeGAIA': 31,
      'tast.login.ExistingUser': 41,
      'tast.login.Offline': 30,
      'tast.login.ProfileExtension': 3,
      'tast.meta.ListTests': 4,
      'tast.meta.RunTests': 12,
      'tast.meta.RunTestsRemoteFixture': 15,
      'tast.metrics.RustBindings': 15,
      'tast.mlservice.WebHandwritingRecognition': 4,
      'tast.nacl.Pnacl': 12,
      'tast.network.ARCMultiNetworking': 66,
      'tast.network.BruschettaConnectivity': 8,
      'tast.network.ConfigBaseline': 9,
      'tast.network.ConfigureServiceForUserProfile': 3,
      'tast.network.DNSProxyQueries': 8,
      'tast.network.DefaultProfile': 2,
      'tast.network.DefaultProfileServices': 3,
      'tast.network.DiagFailDNSResolution': 6,
      'tast.network.Ethernet8021X': 10,
      'tast.network.ResolveLocalHostnameInvalidAddress': 6,
      'tast.network.RoutingFallthrough': 10,
      'tast.network.RoutingHighPriority': 12,
      'tast.network.RoutingIPv4Static': 38,
      'tast.network.RoutingIPv4StaticWithDHCP': 7,
      'tast.network.RoutingIPv6Only': 43,
      'tast.network.RoutingNoIP': 37,
      'tast.network.ShillInitScriptsLoginStartShill': 2,
      'tast.network.ShillStability': 21,
      'tast.network.VPNConnect': 10,
      'tast.network.VPNRouting': 11,
      'tast.oobe.Smoke': 51,
      'tast.peripherals.LaunchAppFromLauncher': 12,
      'tast.peripherals.LaunchAppFromSettings': 12,
      'tast.pita.Install': 223,
      'tast.pita.RuntimeDependencies': 208,
      'tast.platform.CrosDisks': 2,
      'tast.platform.CrosDisksArchive': 11,
      'tast.platform.CrosDisksArchiveBig': 64,
      'tast.platform.CrosDisksFormat': 2,
      'tast.platform.DLCService': 3,
      'tast.platform.Drivefs': 31,
      'tast.platform.Firewall': 2,
      'tast.platform.LocalPerfettoTBMTracedProbes': 12,
      'tast.platform.MLBenchmarkMainline': 3,
      'tast.platform.Memd': 8,
      'tast.platform.P2PClient': 12,
      'tast.platform.P2PServer': 5,
      'tast.platform.PerfettoBatteryDataSource': 11,
      'tast.platform.PerfettoChromeConsumer': 8,
      'tast.platform.PerfettoChromeProducer': 4,
      'tast.platform.PerfettoSystemTracing': 6,
      'tast.platform.Resourced': 4,
      'tast.policy.PluginVMDataCollectionAllowed': 6,
      'tast.power.Reboot': 27,
      'tast.power.SmartDim': 12,
      'tast.printer.Add': 4,
      'tast.printer.AddBrotherPrinter': 5,
      'tast.printer.AddUSBPrinter': 3,
      'tast.printer.GstorasterUnembeddedFont': 2,
      'tast.printer.IPPUSBPPDCopiesSupported': 5,
      'tast.printer.IPPUSBPPDCopiesUnsupported': 5,
      'tast.printer.IPPUSBPPDNoCopies': 6,
      'tast.printer.PrintIPPUSB': 6,
      'tast.printer.PrintUSB': 4,
      'tast.printer.ProxyAdd': 5,
      'tast.printer.ProxyAddBrotherPrinter': 9,
      'tast.printer.ProxyResolutionBrother': 9,
      'tast.printer.RejectDocumentFormat': 3,
      'tast.printer.ResolutionBrother': 5,
      'tast.printer.TestPPDs': 21,
      'tast.printer.USBPrinterTimeout': 26,
      'tast.quicksettings.OpenSettings': 4,
      'tast.rollback.SmokeCleanup': 2,
      'tast.scanner.ADFJustification': 10,
      'tast.scanner.AdvancedScan': 20,
      'tast.scanner.EnumerateIPPUSB': 12,
      'tast.scanner.ScanESCLIPP': 12,
      'tast.secagentd.AgentEvents': 2,
      'tast.secagentd.ProcessEvents': 6,
      'tast.security.ASLR': 5,
      'tast.security.ChromeSandboxed': 6,
      'tast.security.MemoryFileExecTelemetry': 19,
      'tast.security.SELinuxFilesARC': 33,
      'tast.security.SELinuxFilesDataDir': 34,
      'tast.security.SandboxedServices': 3,
      'tast.security.USBGuard': 2,
      'tast.security.UserFilesGuest': 5,
      'tast.security.UserFilesLoggedIn': 13,
      'tast.session.LogoutCleanup': 13,
      'tast.session.MultiUserPolicy': 6,
      'tast.session.OwnershipTaken': 17,
      'tast.session.RejectDuplicate': 4,
      'tast.session.RemoteOwnership': 4,
      'tast.session.RetrieveActiveSessions': 10,
      'tast.session.UserPolicyKeys': 10,
      'tast.shelf.HotseatSmoke': 7,
      'tast.terminal.Crosh': 15,
      'tast.terminal.SSH': 55,
      'tast.ui.ChromeCrashEarly': 11,
      'tast.ui.ChromeCrashLoggedIn': 14,
      'tast.ui.ChromeCrashLoggedInDirect': 12,
      'tast.ui.ChromeCrashLoopV2': 16,
      'tast.ui.ChromeCrashNotLoggedIn': 11,
      'tast.ui.ChromeCrashNotLoggedInDirect': 4,
      'tast.ui.ChromeCrashReporterMetrics': 47,
      'tast.ui.ChromeValidity': 10,
      'tast.ui.ForceRegion': 12,
      'tast.ui.ScreenRecorder': 19,
      'tast.ui.SessionManagerRespawn': 6,
      'tast.ui.StackSampledMetricsV2': 6,
      'tast.ui.WebUIJSErrors': 11,
      'tast.ui.WindowControl': 36,
      'tast.usbip.DeviceList': 2,
      'tast.video.Play': 4,
      'tast.vm.AudioResumeAfterCrasRestarted': 17,
      'tast.vm.ShutdownVMServices': 39,
      'tast.wifi.IWScan': 4,
      'tast.wilco.APIGetConfigurationDataEmpty': 2,
      'tast.wilco.APIGetDriveSystemData': 2,
      'tast.wilco.APIGetProcData': 2,
      'tast.wilco.APIGetSysfsData': 3,
      'tast.wilco.APIGetVPDField': 2,
      'tast.wilco.APIHandleBluetoothDataChanged': 4,
      'tast.wilco.APIHandleECNotification': 2,
      'tast.wilco.APIInvalidEnum': 2,
      'tast.wilco.APIPerformWebRequestError': 2,
      'tast.wilco.ECRTC': 5,
      'tast.wmp.AdminTemplatesLaunch': 39,
      'tast.wmp.DeskTemplatesDelete': 67,
      'tast.wmp.DesksTemplatesBasic': 27,
      'tast.wmp.DesksTemplatesLaunch': 31,
      'tast.wmp.SavedDeskDelete': 42
  }


class Shard:
  """Shard information

  Holds Tests
  Calculate the current used and allocated execution time
  """

  def __init__(self, max_makespan):
    """Initialize with an execution time
    Args:
      max_makespan: allocated execution time
    """
    self.queue = []
    self.max_makespan = max_makespan
    self.makespan = 0

  def add(self, test: TestCase):
    """Add test case to the queue

    Args:
      test: TestCase to add
    """
    self.queue.append(test)
    self.makespan += test.execution_time

  def can_accept(self, test: TestCase):
    """Can the shard accept the test without going over execution time

    Args:
      test: test that could be accepted

    Returns:
      bool result
    """
    return max(self.max_makespan - self.makespan, 0) >= test.execution_time

  def empty(self):
    """Is the shard empty?

    Returns:
      bool """
    return len(self.queue) == 0

  def get_tests(self):
    """Generate a list of assigned tests

    Returns:
      list of tests
    """
    return [test_case.test for test_case in self.queue]


class CrosTestShardingAPI(recipe_api.RecipeApi):
  _MAX_SHARDS = 15

  @staticmethod
  def optimized_shard_allocation(test_suite, total_shards):
    if total_shards == 0:
      total_shards = CrosTestShardingAPI._MAX_SHARDS
    other_makespans = [0, 2700]
    security_bucket = None
    tests_to_bucket = list(test_suite.test_cases.test_cases)
    # TODO (b/277945083): Hard code to group tast.security tests together.
    # Remove once long term solution is implemented.
    security_tests, tests_to_bucket = CrosTestShardingAPI._filter_security_tests(
        tests_to_bucket)
    if len(security_tests) > 0 and total_shards > 1:
      security_bucket = CrosTestShardingAPI._bucket_together(security_tests)
      security_bucket_makespan = CrosTestShardingAPI._get_bucket_execution_time(
          security_tests)
      other_makespans.append(security_bucket_makespan)
      total_shards -= 1

    # Different ways to approach sharding. Shard based on some
    # constraint in space (total_shards) or time (other_makespan).
    shards = CrosTestShardingAPI._shard_constrained(tests_to_bucket,
                                                    total_shards,
                                                    max(other_makespans + [0]))
    if security_bucket:
      shards += security_bucket

    return shards

  @staticmethod
  def _filter_security_tests(test_cases):
    """Get all the security tests_cases
    Args: test_cases: list(test_case)

    Return: list[security test_case id's], list[test_case id's]
    """
    security_tests = []
    other_tests = []
    for test_case in test_cases:
      if 'tast.security' in test_case.id.value:
        security_tests.append(test_case)
      else:
        other_tests.append(test_case)
    return security_tests, other_tests

  @staticmethod
  def _bucket_together(test_cases):
    """Creates one bucket with all test_cases

    Args:
      * test_cases: list[string]

    Returns: List[List[test_case]]
    """
    return [test_cases]

  @staticmethod
  def _get_bucket_execution_time(test_cases):
    """Returns the total execution time of the tests"""
    total_time = 0
    for test_case in test_cases:
      test_sub_name = _get_test_sub_name(test_case.id.value)
      test_time = TestCase.test_times.get(test_sub_name, 1)
      total_time += test_time
    return total_time

  @staticmethod
  def _shard_constrained(test_bucket, requested_shard_count: int,
                         other_makespan: int):
    """Generate testcase objects and distribute them across the shards

    Args:
      test_bucket: list of test_case.proto:TestCase
      requested_shard_count: max number of shards
      other_makespan: Other execution times to consider

    Returns:
      list of shards and list's of their test cases.
    """
    tests_cases = []
    for proto_test in test_bucket:
      tests_cases.append(TestCase(proto_test))
      # min makespan expects
      # - requested shard count
      # - test_cases as a list
      # - other_makespans, list of lengths of other makespans
    shards = CrosTestShardingAPI._constrained_shards(tests_cases,
                                                     requested_shard_count,
                                                     other_makespan)
    return [shard.get_tests() for shard in shards]

  @staticmethod
  def _rebalance_makespan(test_cases: List[TestCase], shards: List[Shard]):
    """Determine a new makespan for the shards based on test_cases
      test_cases : test cases we would like to add
      shards : the available shards to recalculate
    """
    min_shard_makespan = min([shard.makespan for shard in shards])
    total_test_time = sum(
        [test_case.execution_time for test_case in test_cases])
    max_test_time = max([test_case.execution_time for test_case in test_cases])
    avg_makespan = min_shard_makespan + math.ceil(
        total_test_time / len(test_cases))
    new_makespan = max([max_test_time + min_shard_makespan, avg_makespan])

    for shard in shards:
      shard.max_makespan = new_makespan

  @staticmethod
  def _constrained_shards(test_cases: List[TestCase],
                          requested_shard_count: int, requested_makespan: int):
    """Generate shards optimally allocated tests based on a tests execution time.

    Handle the following:
    requested_shard_count | requested_makespan
    0 | 0
    0 | 1
    1 | 0
    1 | 1

    Args:
      test_cases: list of TestCase's
      requested_shard_count: max number of shards
      requested_makespan: Other execution times to consider

    Returns:
      list of shards
    """
    makespan = requested_makespan
    if requested_shard_count != 0 and requested_makespan != 0:
      makespan = 0
    shard_count = requested_shard_count
    # total_test_time = sum([test_case.execution_time for test_case in test_cases])
    # if makespan == 0:
    #   makespan = math.ceil(total_test_time / shard_count)

    # Allocate the shards
    shards = [Shard(makespan) for _ in range(shard_count)]
    test_queue = sorted(test_cases, key=lambda e: e.execution_time,
                        reverse=False)

    #  Pack the shards
    current_shard = 0
    searching = None

    #  Using shards as the primary object
    while len(test_queue) != 0:
      if shards[current_shard].can_accept(test_queue[-1]):
        shards[current_shard].add(test_queue.pop())
        searching = None
        current_shard += 1
      else:
        if searching is None:
          searching = current_shard
        current_shard += 1
      if current_shard >= len(shards):
        current_shard = 0
      if searching == current_shard:
        searching = None
        if len(shards) >= shard_count:
          CrosTestShardingAPI._rebalance_makespan(test_queue, shards)
          makespan = shards[0].max_makespan
        #  For now we do not extend the shard count.
        # else:
        #   new_shard = Shard(makespan)
        #   new_shard.add(test_queue.pop())
        #   shards.append(new_shard)
      if len(test_queue) == 0:
        break

    #  remove empty shards
    shards[:] = filterfalse(lambda shard: shard.empty(), shards)
    return shards


def _get_test_sub_name(test_name):
  return '.'.join(test_name.split('.')[:3])
