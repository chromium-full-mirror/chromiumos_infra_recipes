# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building a Parallels image for testing.

This recipe runs on a lab drone and takes control of a physical DUT
to build a new Parallels VM image, for later use in automated testing.

This recipe involves booting up Windows in a virtual machine on the DUT.
The caller is responsible for ensuring this is only invoked in contexts
where the necessary license(s) have been obtained. Contact parallels-cros@
for more details.

This recipe is invoked as part of uprev_parallels_pin.
"""

from collections import namedtuple
from pathlib import Path
from typing import Generator
from typing import Tuple

from PB.recipes.chromeos.build_parallels_image import BuildParallelsImageProperties
from PB.test_platform.taskstate import TaskState
from PB.testplans.generate_test_plan import BuildPayload
from recipe_engine import post_process
from recipe_engine.post_process import GetBuildProperties
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_api import StepFailure
from recipe_engine.recipe_test_api import RecipeTestApi
from recipe_engine.recipe_test_api import TestData

DEPS = [
    'depot_tools/gsutil',
    'recipe_engine/file',
    'recipe_engine/json',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
    'recipe_engine/time',
    'easy',
    'phosphorus',
    'tast_exec',
    'tast_results',
    'test_util',
]


PROPERTIES = BuildParallelsImageProperties

_GS_BROWSER_PREFIX = 'https://console.cloud.google.com/storage/browser'
_SYS_LOG_DIR = '/var/log'
_DUT_STATE_NEEDS_REPAIR = 'needs_repair'
_DUT_STATE_READY = 'ready'

_TAST_NAME = 'pita.CreateFromIso.uprev'

BuildPath = namedtuple('BuildPath', ['bucket', 'path'])
VersionPin = namedtuple('VersionPin', ['version', 'test_image'])


def RunSteps(api: RecipeApi, properties: BuildParallelsImageProperties) -> None:
  with api.step.nest('validate properties') as presentation:
    if not properties.build_gs_bucket:
      raise StepFailure('must set build_gs_bucket')
    if not properties.build_gs_path:
      raise StepFailure('must set build_gs_path')
    if not properties.test_image_gs_bucket:
      raise StepFailure('must set test_image_gs_bucket')
    if not properties.test_image_gs_path:
      raise StepFailure('must set test_image_gs_path')
    if not properties.parallels_version:
      raise StepFailure('must set parallels_version')

    presentation.step_text = 'all properties good'

  if not properties.test_mode:
    # Build a new VM image.
    image_name, size, sha256 = build_vm_image(api, properties)
  else:
    # Populate some dummy result values.
    image_name = 'test_image.zip'
    size = 1234567890
    sha256 = '1234567890abcdef1234567890abcdef'

  # Set recipe outputs.
  with api.step.nest('set output properties') as step:
    step.properties['image_name'] = image_name
    step.properties['image_size'] = size
    step.properties['image_sha256'] = sha256


def build_vm_image(
    api: RecipeApi,
    properties: BuildParallelsImageProperties) -> Tuple[str, int, str]:
  """Builds a new VM image for testing.

  Returns:
    image_name(str): The name of the generated image.
    image_size(int): The size of the generated image, in bytes.
    image_hash(str): The base64-encoded SHA256 hash of the generated image.
  """
  # Download tast runner.
  test_artifacts_dir = api.path.mkdtemp(prefix='test-artifacts')
  build_payload = BuildPayload(artifacts_gs_bucket=properties.build_gs_bucket,
                               artifacts_gs_path=properties.build_gs_path)
  api.tast_exec.download_tast(build_payload, test_artifacts_dir)

  # Provision the DUT with the requested version of CrOS and pita DLC.
  with api.step.nest('provision DUT') as presentation:
    presentation.links['build artifacts'] = '{}/{}/{}'.format(
        _GS_BROWSER_PREFIX, properties.build_gs_bucket,
        properties.build_gs_path)
    # In case the following provisioning or image build operation fails,
    # leave the DUT marked as needing repair. If the operation succeeded,
    # we can revert it to being ready.
    api.phosphorus.build_parallels_image_save(_DUT_STATE_NEEDS_REPAIR)
    api.phosphorus.build_parallels_image_provision('gs://{}/{}'.format(
        properties.build_gs_bucket, properties.build_gs_path))

  image_dir = api.path.mkdtemp(prefix='parallels-image')
  image_name = 'pre_pluginvm_image_{}_{}.zip'.format(
      properties.parallels_version,
      api.time.utcnow().strftime('%Y%m%d'))
  image_path = image_dir / image_name

  # Invoke tast to build the VM image.
  invoke_tast(api, test_artifacts_dir, build_payload, image_path)

  upload_path = '{}/{}'.format(properties.test_image_gs_path, image_name)
  with api.step.nest('upload image') as presentation:
    presentation.step_text = 'name: {}'.format(image_name)
    presentation.links['destination directory'] = '{}/{}/{}'.format(
        _GS_BROWSER_PREFIX, properties.test_image_gs_bucket,
        properties.test_image_gs_path)

    # Upload the file to google storage (but do not overwrite anything
    # existing (-n)).
    api.gsutil.upload(image_path, properties.test_image_gs_bucket, upload_path,
                      args=['-n'])

    if properties.user_acls or properties.group_acls:
      with api.step.nest('set image permissions on destination'):
        cmd = ['acl', 'ch', '-r']
        for user_acl in properties.user_acls:
          cmd += ['-u', user_acl]

        for group_acl in properties.group_acls:
          cmd += ['-g', group_acl]

        cmd += [
            'gs://{}/{}'.format(properties.test_image_gs_bucket, upload_path)
        ]

        api.gsutil(cmd)

    presentation.links['uploaded image'] = '{}/{}/{}'.format(
        _GS_BROWSER_PREFIX, properties.test_image_gs_bucket, upload_path)

  with api.step.nest('mark DUT ready') as presentation:
    # Image build succeeded, so mark the DUT as still being in a good state.
    api.phosphorus.build_parallels_image_save(_DUT_STATE_READY)

  with api.step.nest('compute image size and sha256') as presentation:
    sha256 = api.easy.stdout_step(
        'get file sha256 hash', ['sha256sum', image_path],
        test_stdout=b'fedbca09876543211234567890abcdef /path/to/file').split(
            b' ', 1)[0].decode('utf-8')
    size = int(
        api.easy.stdout_step('get file length',
                             ['stat', '--printf=%s', image_path],
                             test_stdout='9123456789'))

    # Present results in same format as go/tast-writing#external-data-files.
    results = {
        'url':
            'gs://{}/{}'.format(properties.test_image_gs_bucket, upload_path),
        'size':
            size,
        'sha256sum':
            sha256,
    }
    presentation.logs['metadata'] = api.json.dumps(results, indent=2)
  return image_name, size, sha256


def invoke_tast(api: RecipeApi, test_artifacts_dir: Path,
                build_payload: BuildPayload, dest_path: Path) -> None:
  """Runs tast to build the new VM image.

  Args:
    test_artifacts_dir (Path): The location of test artifacts produced by the
      build.
    build_payload (BuildPayload): Describes where the artifact is on GS.
    dest_path (Path): The location that the produced VM image should be copied
      to (on the local disk).
  """
  with api.step.nest('invoke tast') as presentation:
    tast_results_dir = api.path.mkdtemp(prefix='tast-results')
    tests = api.tast_exec.run_direct(
        api.phosphorus.read_dut_hostname(),
        api.tast_exec.TastInputs([_TAST_NAME], test_artifacts_dir,
                                 build_payload,
                                 run_args=['-var=pita.windowsLicensed=true']),
        tast_results_dir)

    try:
      src_path = tast_results_dir / 'tests' / _TAST_NAME / 'PvmDefault.zip'

      # Move VM image out of the test results directory (to avoid it getting
      # uploaded with test logs) and rename it to its final name.
      cmd = ['mv', src_path, dest_path]
      api.step('rename VM image', cmd)
      image_exists = True
    except StepFailure:
      # Move failed, tast did not produce VM image.
      image_exists = False

    # Parse tast results and upload logs for archival purposes
    result = api.tast_results.get_results(tast_results_dir, 'parallels_uprev',
                                          'first', tests)
    presentation.links['tast_logs'] = result.log_url

    api.tast_results.record_logs(_SYS_LOG_DIR)

    if result.state.verdict != TaskState.VERDICT_PASSED:
      # Tast failed or failed to reach a result.
      results, _ = api.tast_results.convert_results(result)
      is_empty = result.state.verdict == TaskState.VERDICT_UNSPECIFIED
      api.tast_results.print_results(results.failures, is_empty)

      raise api.step.StepFailure(
          'image build failed: {} failed'.format(_TAST_NAME))
    if not image_exists:
      # Tast reports it has succeeded but the image could not be found.
      raise api.step.StepFailure(
          'image build failed: {} passed but image could not be found'.format(
              _TAST_NAME))


def GenTests(api: RecipeTestApi) -> Generator[TestData, None, None]:
  good_props = {
      '$chromeos/tast_results': {
          'archive_gs_bucket': 'chromeos-parallels-uprev-archive',
      },
      'build_gs_bucket': 'chromeos-image-archive',
      'build_gs_path': 'uprev-parallels-pin/R88-13547.0.0-11193-12345',
      'parallels_version': '1.2.3.4',
      'test_image_gs_bucket': 'chromeos-test-assets-private',
      'test_image_gs_path': 'tast/pita/pita',
      'user_acls': ['owner@google.com:OWNER', 'reader@google.com:READ'],
      'group_acls': ['aclgroup@google.com:READ']
  }

  # Test missing recipe parameters.
  props = good_props.copy()
  del props['build_gs_bucket']
  yield api.test(
      'no-build_gs_bucket',
      api.test_util.test_build(builder='build-parallels-image').build,
      api.properties(**props),
      api.phosphorus.properties(),
      api.post_check(post_process.DoesNotRun, 'provision DUT'),
      status='FAILURE',
  )

  props = good_props.copy()
  del props['build_gs_path']
  yield api.test(
      'no-build_gs_path',
      api.test_util.test_build(builder='build-parallels-image').build,
      api.properties(**props),
      api.phosphorus.properties(),
      api.post_check(post_process.DoesNotRun, 'provision DUT'),
      status='FAILURE',
  )

  props = good_props.copy()
  del props['test_image_gs_bucket']
  yield api.test(
      'no-test_image_gs_bucket',
      api.test_util.test_build(builder='build-parallels-image').build,
      api.properties(**props),
      api.phosphorus.properties(),
      api.post_check(post_process.DoesNotRun, 'provision DUT'),
      status='FAILURE',
  )

  props = good_props.copy()
  del props['test_image_gs_path']
  yield api.test(
      'no-test_image_gs_path',
      api.test_util.test_build(builder='build-parallels-image').build,
      api.properties(**props),
      api.phosphorus.properties(),
      api.post_check(post_process.DoesNotRun, 'provision DUT'),
      status='FAILURE',
  )

  props = good_props.copy()
  del props['parallels_version']
  yield api.test(
      'no-parallels_version',
      api.test_util.test_build(builder='build-parallels-image').build,
      api.properties(**props),
      api.phosphorus.properties(),
      api.post_check(post_process.DoesNotRun, 'provision DUT'),
      status='FAILURE',
  )

  failureJson = api.json.loads('''[{
    "name": "pita.CreateFromIso.uprev",
    "pkg": "chromiumos/tast/local/bundles/pita",
    "additionalTime": 30000000000,
    "desc": "Description",
    "contacts": [
      "someone@chromium.org"
    ],
    "attr": [
      "name:pita.CreateFromIso.uprev",
      "bundle:cros",
      "dep:chrome"
    ],
    "data": null,
    "softwareDeps": [
      "chrome"
    ],
    "timeout": 300000000000,
    "errors": [
      {
        "reason": "Lost SSH connection to DUT"
      }
    ],
    "start": "2020-01-27T15:16:15.146771555-08:00",
    "end": "2020-01-27T15:16:33.420622341-08:00",
    "outDir": "/tmp/vm-test-results.JxZdcJ/tests/pita.CreateFromIso.uprev",
    "skipReason": ""
  }]''')

  failureJsonl = '\n'.join(api.json.dumps(x) for x in failureJson)

  # Tast fails
  yield api.test(
      'tast-failure',
      api.test_util.test_build(builder='build-parallels-image').build,
      api.properties(**good_props),
      api.phosphorus.properties(),
      api.tast_exec.simulate_test_list_ret('pita.CreateFromIso.uprev'),
      api.post_check(post_process.MustRun, 'provision DUT'),
      api.step_data(
          'invoke tast.process tast output.read streamed_results.jsonl',
          api.file.read_text(failureJsonl)),
      api.post_check(post_process.DoesNotRun, 'upload image'),
      status='FAILURE',
  )

  successJson = api.json.loads('''[{
    "name": "pita.CreateFromIso.uprev",
    "pkg": "chromiumos/tast/local/bundles/pita",
    "additionalTime": 30000000000,
    "desc": "Description",
    "contacts": [
      "someone@chromium.org"
    ],
    "attr": [
      "name:pita.CreateFromIso.uprev",
      "bundle:cros",
      "dep:chrome"
    ],
    "data": null,
    "softwareDeps": [
      "chrome"
    ],
    "timeout": 300000000000,
    "errors": null,
    "start": "2020-01-27T15:16:15.146771555-08:00",
    "end": "2020-01-27T15:16:33.420622341-08:00",
    "outDir": "/tmp/vm-test-results.JxZdcJ/tests/pita.CreateFromIso.uprev",
    "skipReason": ""
  }]''')

  successJsonl = '\n'.join(api.json.dumps(x) for x in successJson)

  # Tast appears to succeed, but not VM image was produced.
  yield api.test(
      'tast-no-image',
      api.test_util.test_build(builder='build-parallels-image').build,
      api.properties(**good_props),
      api.phosphorus.properties(),
      api.tast_exec.simulate_test_list_ret('pita.CreateFromIso.uprev'),
      api.post_check(post_process.MustRun, 'provision DUT'),
      api.step_data(
          'invoke tast.process tast output.read streamed_results.jsonl',
          api.file.read_text(successJsonl)),
      api.step_data('invoke tast.rename VM image', retcode=1),
      api.post_check(post_process.DoesNotRun, 'upload image'),
      status='FAILURE',
  )

  # Success
  yield api.test(
      'success',
      api.test_util.test_build(builder='build-parallels-image').build,
      api.properties(**good_props), api.phosphorus.properties(),
      api.tast_exec.simulate_test_list_ret('pita.CreateFromIso.uprev'),
      api.step_data(
          'invoke tast.process tast output.read streamed_results.jsonl',
          api.file.read_text(successJsonl)),
      api.post_check(post_process.MustRun, 'provision DUT'),
      api.post_check(post_process.MustRun, 'upload image'),
      api.post_check(post_process.MustRun, 'compute image size and sha256'),
      api.post_check(lambda check, steps: check(
          GetBuildProperties(steps).get('image_name', '') ==
          'pre_pluginvm_image_1.2.3.4_20120514.zip')),
      api.post_check(lambda check, steps: check(
          GetBuildProperties(steps).get('image_size', -1) == 9123456789)),
      api.post_check(lambda check, steps: check(
          GetBuildProperties(steps).get('image_sha256', '') ==
          'fedbca09876543211234567890abcdef')))

  # Test mode
  props = good_props.copy()
  props['test_mode'] = True
  yield api.test(
      'testmode',
      api.test_util.test_build(builder='build-parallels-image').build,
      api.properties(**props), api.phosphorus.properties(),
      api.post_check(lambda check, steps: check(
          GetBuildProperties(steps).get('image_name', '') == 'test_image.zip')),
      api.post_check(lambda check, steps: check(
          GetBuildProperties(steps).get('image_size', -1) == 1234567890)),
      api.post_check(lambda check, steps: check(
          GetBuildProperties(steps).get('image_sha256', '') ==
          '1234567890abcdef1234567890abcdef')))
