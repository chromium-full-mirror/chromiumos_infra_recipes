# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test reven (aka ChromeOS Flex) installation.

   Reven can be installed by end users from a USB device. This operation
   can be tested with the OsInstall tast test, but that test can't be
   run as part of the regular suite of VM tests as it requires some
   additional setup, which this recipe provides. Specifically, OS
   installation shuts the machine down at the end. The test then waits
   for the machine to be powered back up in the installed state to
   verify the installation succeeded.

   Here's how the recipe operates:

   1. An empty target disk is created as the destination to install to.

   2. A BuildPayload is downloaded and prepped. The board being tested
      is reven-vmtest. That board inherits from the base reven board and
      is specifically intended for VM tests. The source disk must be
      tweaked slightly to make it look like an installer image, see
      `make_into_installer`.

   3. A VM is launched with two disks: the source installer disk and the
      empty target disk.

   4. A future is spawned to run the OsInstall tast test.

   5. The recipe then starts polling, waiting for the VM to shut down.

   6. Once the VM shuts down, a new VM is launched with just the target
      disk, which should now contain the installed image.

   7. Meanwhile the future with the tast test is still running. Once the
      VM boots back up the test will reconnect to it and verify if
      installation succeeded.
"""

import copy
from typing import Generator
from typing import List

import gevent
from RECIPE_MODULES.chromeos.tast_exec.api import TastExecApi

from PB.recipe_engine import result as result_pb2
from PB.recipes.chromeos.os_install_vm import OsInstallVmProperties
from recipe_engine import post_process
from recipe_engine.config_types import Path
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_api import StepFailure
from recipe_engine.recipe_test_api import RecipeTestApi
from recipe_engine.recipe_test_api import StepTestData
from recipe_engine.recipe_test_api import TestData

DEPS = [
    'recipe_engine/file',
    'recipe_engine/futures',
    'recipe_engine/json',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'easy',
    'failures',
    'tast_exec',
    'tast_results',
]


PROPERTIES = OsInstallVmProperties


def make_into_installer(api: RecipeApi, image_path: Path) -> None:
  """Modify the raw disk image at `image_path` to make it installable.

  The disk layout of the reven-vmtest board is slightly different from
  the reven board; to allow update testing to work it has a full-size
  ROOT-B partition. The OS installer distinguishes an installer from an
  installed image by checking if the ROOT-A and ROOT-B partitions have
  different sizes, so to make the image being tested look like an
  installer, shrink the ROOT-B partition down to a single block.
  """
  with api.step.nest('make image into installer'):
    # The root-b partition number.
    root_b_num = 5

    # Get the partition info.
    stdout = api.easy.stdout_step(
        'get root-b partition',
        ['sgdisk', '--info={}'.format(root_b_num), image_path]).decode()

    # Parse the output. Each line is in "key: value" format.
    lines = stdout.splitlines()
    first_sector = None
    type_guid = None
    name = None
    for line in lines:
      key, val = line.split(': ')[:2]
      if key == 'First sector':
        first_sector = val.split()[0]
      elif key == 'Partition GUID code':
        type_guid = val[:36]
      elif key == 'Partition name':
        name = val

    # Validate that the partition's name and type are as expected.
    if name != "'ROOT-B'":
      raise StepFailure('unexpected partition name: {}'.format(name))
    if type_guid != '3CB8E202-3B7E-47DD-8A3C-7FF2A13CFCEC':
      raise StepFailure('unexpected type GUID: {}'.format(type_guid))

    api.step(
        'make image into an installer',
        [
            'sgdisk',
            # Delete the original partition.
            '--delete={}'.format(root_b_num),
            # Make a new one in the same place but with a size of one block.
            '--new={root_b_num}:{first_sector}:{first_sector}'.format(
                root_b_num=root_b_num, first_sector=first_sector),
            # Set the partition's type GUID.
            '--typecode={}:{}'.format(root_b_num, type_guid),
            # Set the partition's name.
            '--change-name={}:{}'.format(root_b_num, name),
            image_path
        ])


def run_tast(api: RecipeApi, properties: OsInstallVmProperties,
             vm: TastExecApi.VmInfo, tast_inputs: TastExecApi.TastInputs,
             test_results_dir: Path) -> result_pb2.RawResult:
  # If tast_timeout_in_seconds is set (which only happens in tests), use
  # gevent.sleep to make this function take some small amount of
  # time. This is necessary because the recipe expects the tast-run
  # future to keep running until the end, so in the successful test case
  # it needs to run for longer than zero seconds.
  if properties.tast_timeout_in_seconds:
    gevent.sleep(properties.tast_timeout_in_seconds)

  tests = api.tast_exec.run_direct(vm.address(), tast_inputs, test_results_dir)
  test_results = api.tast_results.get_results(
      test_results_path=test_results_dir, suite_name='os_install',
      tag='os_install', tests=tests)
  results, _ = api.tast_results.convert_results(test_results)
  api.tast_results.print_results(results.failures, False)
  return api.failures.aggregate_failures(results)


def RunSteps(api: RecipeApi,
             properties: OsInstallVmProperties) -> result_pb2.RawResult:
  # Get timing values from properties or defaults. In normal usage the
  # defaults are used, but they are set to different values during
  # testing of the recipe itself.
  poll_interval_in_seconds = properties.poll_interval_in_seconds or 15
  # Default: 10 minutes
  tast_timeout_in_seconds = properties.tast_timeout_in_seconds or 10 * 60

  # Set up temporary directories.
  test_artifacts_dir = api.path.mkdtemp(prefix='test-artifacts')
  test_results_dir = api.path.mkdtemp(prefix='test-results')
  image_archive_dir = api.path.mkdtemp(prefix='image-archive')

  # Download tast artifacts.
  api.tast_exec.download_tast(properties.build_payload, test_artifacts_dir)

  # Download and prepare the installer image.
  modify_image = lambda image_path: make_into_installer(api, image_path)
  qcow_image_path = api.tast_exec.download_vm(properties.build_payload,
                                              image_archive_dir,
                                              modify_image=modify_image)

  # Create empty install target.
  install_target_image_path = image_archive_dir / 'install_target.qcow2'
  api.step('create empty install image', [
      'qemu-img', 'create', '-f', 'qcow2',
      str(install_target_image_path), '24G'
  ])

  # Prepare the initial VM context which has both the installer and
  # target disks attached.
  vm_context = api.tast_exec.create_qemu_vm_context(
      qcow_image_path, second_image_path=install_target_image_path)

  tast_inputs = api.tast_exec.TastInputs(
      ['osinstall.OsInstall'],
      test_artifacts_dir,
      properties.build_payload,
      # Set a timeout for the test. Note that this is different from
      # setting a timeout on the whole tast-run step, which the
      # tast_exec module already does.
      run_args=['-timeout', str(tast_timeout_in_seconds)])

  with api.step.nest('run OS install test'):
    with vm_context() as vm:
      tast_future = api.futures.spawn(run_tast, api, properties, vm,
                                      tast_inputs, test_results_dir)

      # Start a polling loop waiting for the VM to exit. The current
      # greenlet will be mostly blocked during this loop.
      with api.step.nest('wait for install to complete'):
        loop = True
        while loop:
          done_futures = api.futures.wait([tast_future],
                                          timeout=poll_interval_in_seconds)
          if done_futures:
            raise StepFailure('tast exited early')

          # Exit the loop once the VM process is done.
          if not api.tast_exec.is_vm_running(vm.pid_file):
            loop = False

    with api.step.nest('boot installed system'):
      # Create a new VM. This one has just the target installation
      # disk. Note that at this point the tast future is still
      # running, and it's important that this is run in the same step,
      # otherwise the previous step would block waiting for all futures to
      # complete.
      vm_context = api.tast_exec.create_qemu_vm_context(
          install_target_image_path)
      with vm_context():
        # Wait for the tast future to complete and return its result (or
        # propagate an exception). No timeout is needed here as the tast
        # run already has a timeout.
        return tast_future.result()


def GenTests(api: RecipeTestApi) -> Generator[TestData, None, None]:
  good_root_b = '''Partition GUID code: 3CB8E202-3B7E-47DD-8A3C-7FF2A13CFCEC (ChromeOS root)
Partition unique GUID: 43D905A3-811A-3548-8F2B-A4ECC2AABE59
First sector: 233472 (at 114.0 MiB)
Last sector: 237567 (at 116.0 MiB)
Partition size: 4096 sectors (2.0 MiB)
Attribute flags: 0000000000000000
Partition name: 'ROOT-B'
'''

  build_payload = {
      'artifacts_gs_bucket': 'artifacts-bucket',
      'artifacts_gs_path': 'artifacts-path'
  }

  success_json = [{
      'name': 'osinstall.OsInstall',
      'pkg': 'chromiumos/tast/remote/bundles/osinstall',
      'additionalTime': 30000000000,
      'desc': 'Description',
      'contacts': ['someone@chromium.org'],
      'attr': ['name:osinstall.OsInstall', 'bundle:cros', 'dep:chrome'],
      'data': None,
      'softwareDeps': ['chrome'],
      'timeout': 300000000000,
      'errors': None,
      'start': '2022-05-17T10:11:00.989201834-05:00',
      'end': '2022-05-17T10:21:01.285837834-05:00',
      'outDir': '/tmp/vm-test-results.GyXptL/tests/osinstall.OsInstall',
      'skipReason': ''
  }]

  failure_json = copy.deepcopy(success_json)
  failure_json[0]['errors'] = [{'reason': 'installer is broken'}]

  def make_results_jsonl(src: List[str]) -> StepTestData:
    jsonl = '\n'.join(api.json.dumps(x) for x in src)
    return api.file.read_text(jsonl)

  # Test unexpected ROOT-B partition name.
  yield api.test(
      'bad_root_b_name',
      api.properties(build_payload=build_payload, poll_interval_in_seconds=0.1),
      api.step_data(
          'setup vm image.make image into installer.get root-b partition',
          stdout=api.raw_io.output("Partition name: 'ROOT-A'")),
      api.post_check(post_process.StepFailure,
                     'setup vm image.make image into installer'),
      api.post_check(post_process.ResultReason,
                     "unexpected partition name: 'ROOT-A'"),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  # Test unexpected ROOT-B partition type.
  yield api.test(
      'bad_root_b_type',
      api.properties(build_payload=build_payload, poll_interval_in_seconds=0.1),
      api.step_data(
          'setup vm image.make image into installer.get root-b partition',
          stdout=api.raw_io.output(
              "Partition GUID code: somebadval\nPartition name: 'ROOT-B'")),
      api.post_check(post_process.StepFailure,
                     'setup vm image.make image into installer'),
      api.post_check(post_process.ResultReason,
                     'unexpected type GUID: somebadval'),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  # Test "tast run" exiting before the VM exits.
  yield api.test(
      'tast_exits_early',
      api.properties(build_payload=build_payload, poll_interval_in_seconds=0.1,
                     tast_timeout_in_seconds=0),
      api.tast_exec.simulate_test_list_ret('osinstall.OsInstall'),
      api.step_data(
          'setup vm image.make image into installer.get root-b partition',
          stdout=api.raw_io.output(good_root_b)),
      api.post_check(post_process.StepFailure,
                     'run OS install test.wait for install to complete'),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  # Test tast failure.
  yield api.test(
      'tast_test_fails',
      api.properties(build_payload=build_payload, poll_interval_in_seconds=0.1,
                     tast_timeout_in_seconds=1),
      api.tast_exec.simulate_test_list_ret('osinstall.OsInstall'),
      api.step_data(
          'setup vm image.make image into installer.get root-b partition',
          stdout=api.raw_io.output(good_root_b)),
      api.step_data(
          'run OS install test.wait for install to complete.check if VM running (2)',
          retcode=1,
      ),
      api.step_data(
          'run OS install test.process tast output.read streamed_results.jsonl',
          make_results_jsonl(failure_json)),
      api.post_check(post_process.StepFailure, 'run OS install test'),
      api.post_check(post_process.ResultReasonRE, 'installer is broken'),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  # Test successful run.
  yield api.test(
      'success',
      api.properties(build_payload=build_payload, poll_interval_in_seconds=0.1,
                     tast_timeout_in_seconds=1),
      api.tast_exec.simulate_test_list_ret('osinstall.OsInstall'),
      api.step_data(
          'setup vm image.make image into installer.get root-b partition',
          stdout=api.raw_io.output(good_root_b)),
      api.step_data(
          'run OS install test.wait for install to complete.check if VM running (2)',
          retcode=1,
      ),
      api.step_data(
          'run OS install test.process tast output.read streamed_results.jsonl',
          make_results_jsonl(success_json)),
      api.post_check(post_process.StepSuccess, 'run OS install test'),
      api.post_process(post_process.DropExpectation))
