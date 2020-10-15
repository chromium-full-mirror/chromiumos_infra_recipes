# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for generating Parallels uprev CLs.

This recipe generates CLs to uprev Parallels binaries. As part of these
CLs, a new Parallels VM image is produced for testing.

This recipe involves booting up Windows in a virtual machine. The
caller is responsible for ensuring this is only invoked in contexts
where the necessary license(s) have been obtained.
"""
from collections import namedtuple

import json
import re

from recipe_engine import post_process
from recipe_engine.recipe_api import StepFailure
from PB.chromite.api.packages import UprevVersionedPackageRequest
from PB.test_platform.taskstate import TaskState

DEPS = [
    'depot_tools/gsutil',
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/scheduler',
    'recipe_engine/step',
    'recipe_engine/time',
    'build_menu',
    'cros_artifacts',
    'cros_build_api',
    'cros_infra_config',
    'cros_sdk',
    'cros_source',
    'easy',
    'gerrit',
    'git',
    'repo',
    'naming',
    'skylab',
    'test_util',
    'tast_exec',
    'tast_results',
]

from PB.recipes.chromeos.uprev_parallels_pin import UprevParallelsPinProperties

PROPERTIES = UprevParallelsPinProperties

_PANTHEON_PREFIX = 'https://pantheon.corp.google.com/storage/browser'
_BUILD_STEP_NAME = 'build chromiumos with upreved Parallels'
_IMAGE_STEP_NAME = 'build VM image'
# TODO(meiring): Fix up once the real process to generate a VM image is
# available and is enabled on betty.
_TAST_NAME = 'example.DataFiles'
_SYS_LOG_DIR = '/var/log'

BuildPath = namedtuple('BuildPath', ['bucket', 'path'])
VersionPin = namedtuple('VersionPin', ['version', 'test_image'])


def RunSteps(api, properties):
  with api.step.nest('validate properties') as presentation:
    if not properties.HasField('package_info'):
      raise ValueError('must set package_info')
    if not properties.upstream_gs_bucket:
      raise ValueError('must set upstream_gs_bucket')
    if not properties.upstream_gs_path:
      raise ValueError('must set upstream_gs_path')
    if not properties.test_image_gs_bucket:
      raise ValueError('must set test_image_gs_bucket')
    if not properties.test_image_gs_path:
      raise ValueError('must set test_image_gs_path')
    if not properties.version_file:
      raise ValueError('must set version_file')

    presentation.step_text = 'all properties good'

  package = properties.package_info

  upstream_version = get_upstream_version(api, properties)

  # Build a version of Chrome OS with the new Parallels version. If build
  # is not required (because upstream_version is the current version), returns
  # None.
  build_path = build_os_with_uprev(api, properties, package, upstream_version)
  if build_path:
    # Build a new VM image.
    test_image = build_vm_image(api, properties, build_path, upstream_version)
    # Update VERSION-PIN
    new_pin = VersionPin(upstream_version, test_image)
    commit_pin_uprev(api, properties, package, new_pin)


def build_os_with_uprev(api, properties, package, upstream_version):
  """Builds a version of Chrome OS with given version of the Parallels
  package.

  The build will still contain an old VM image for testing.

  Args:
    package (chromiumos.PackageInfo): the identify of the Parallels package.
    upstream_version (str): the version of Parallels to include in the build.

  Returns:
    BuildPath: where the build artifacts were uploaded."""
  with api.step.nest(_BUILD_STEP_NAME) as presentation:
    with api.build_menu.configure_builder() as config, \
        api.build_menu.setup_workspace_and_chroot():

      version_pin = get_version_pin(api, properties)
      if not is_version_after(upstream_version, version_pin.version):
        presentation.step_text = 'build not required, Parallels already up to date.'
        return None

      uprev_package(api, properties, package, upstream_version)

      env_info = api.build_menu.setup_sysroot_and_determine_relevance()
      packages = env_info.packages

      # Artifacts are frequently of use even if the build failed.  For example, it
      # is likely that the developer will want to see the ebuild logs from install
      # packages when that step fails, or even if build images fail afterward.
      publish = True
      try:
        api.build_menu.bootstrap_sysroot_and_install_packages(config, packages)
        api.build_menu.build_and_test_images(config)
      except StepFailure:
        publish = False
        raise
      finally:
        api.build_menu.upload_artifacts(config, disable_publish=not publish)

      with api.step.nest('get artifacts path'):
        gs_path = api.cros_artifacts.artifacts_gs_path(
            config.id.name, api.build_menu.build_target, config.id.type)
        presentation.links['build artifacts'] = "{}/{}/{}".format(
            _PANTHEON_PREFIX, config.artifacts.artifacts_gs_bucket, gs_path)
        return BuildPath(config.artifacts.artifacts_gs_bucket, gs_path)


def uprev_package(api, properties, package, to_version):
  """Uprevs the Parallels package to the given version.

  The Parallels package will be upreved on the local checkout to the given
  version.

  Args:
    package (chromiumos.PackageInfo): the package to uprev.
    to_version (str): the version to uprev to.
  """
  package_title = api.naming.get_package_title(package)
  with api.step.nest('try uprev {}'.format(package_title)) as presentation:
    # Update pinned version to to_version, but don't change the test_image.
    version_pin = get_version_pin(api, properties)
    version_pin = VersionPin(to_version, version_pin.test_image)
    set_version_pin(api, properties, version_pin)

    request = UprevVersionedPackageRequest(
        chroot=api.cros_sdk.chroot,
        package_info=package,
        versions=[
            # Pass a dummy GitRef, as one is required by the
            # UprevVersionedPackage endpoint.
            UprevVersionedPackageRequest.GitRef(
                repository=properties.upstream_gs_bucket, ref=to_version,
                revision='')
        ],
        build_targets=[])
    response = api.cros_build_api.PackageService.UprevVersionedPackage(
        request, name='uprev versioned package')

    presentation.logs['uprev versions'] = [
        response.version for response in response.responses
    ]
    return


def build_vm_image(api, properties, artifacts_path, parallels_version):
  """Builds a new VM image for testing.

  Args:
    artifacts_path(BuildPath): The location of build output artifacts.
    parallels_version(str): The Parallels version included in the given build.

  Returns:
    dict: The details of the new test image."""
  with api.step.nest(_IMAGE_STEP_NAME) as presentation:
    presentation.links['destination directory'] = '{}/{}/{}'.format(
        _PANTHEON_PREFIX, properties.test_image_gs_bucket,
        properties.test_image_gs_path)

    test_artifacts_dir = api.path.mkdtemp(prefix='test-artifacts')
    api.tast_exec.download_tast(artifacts_path.bucket, artifacts_path.path,
                                test_artifacts_dir)

    image_archive_dir = api.path.mkdtemp(prefix='image-archive')
    qcow_image_path, private_key_path = api.tast_exec.download_vm(
        artifacts_path.bucket, artifacts_path.path, image_archive_dir)

    image_dir = api.path.mkdtemp(prefix='parallels-image')
    image_name = 'pre_pluginvm_image_{}_{}.zip'.format(
        parallels_version,
        api.time.utcnow().strftime("%Y%m%d"))
    image_path = image_dir.join(image_name)

    # Invoke tast to build the VM image.
    invoke_tast(api, test_artifacts_dir, qcow_image_path, private_key_path,
                image_path)

    upload_path = '{}/{}'.format(properties.test_image_gs_path, image_name)
    with api.step.nest('upload image') as upload_step:
      upload_step.step_text = 'name: {}'.format(image_name)

      # Upload the file to google storage (but do not overwrite anything
      # existing (-n)).
      api.gsutil.upload(image_path, properties.test_image_gs_bucket,
                        upload_path, args=['-n'])

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

    sha256 = api.easy.stdout_step(
        'get file sha256 hash', ['sha256sum', image_path],
        test_stdout='1234567890abcdef1234567890abcdef /path/to/file').split(
            ' ', 1)[0]
    size = int(
        api.easy.stdout_step('get file length',
                             ['stat', '--printf=%s', image_path],
                             test_stdout="9123456789"))

    image_details = {
        'url':
            'gs://{}/{}'.format(properties.test_image_gs_bucket, upload_path),
        'size':
            size,
        'sha256sum':
            sha256,
    }
    presentation.links['uploaded image'] = '{}/{}/{}'.format(
        _PANTHEON_PREFIX, properties.test_image_gs_bucket, upload_path)
    presentation.logs['metadata'] = json.dumps(image_details)
    # This blob is defined by tast. See go/tast-writing#external-data-files.
    return image_details


def invoke_tast(api, test_artifacts_dir, qcow_image_path, private_key_path,
                dest_path):
  """Runs tast to build the new VM image.

  Args:
    test_artifacts_dir(Path): The location of test artifacts produced by the
      build.
    qcow_image_path(Path): The location of the qcow-format VM image.
    private_key_path(Path): The location of the private key that can be used
      to authenticate to the VM.
    dest_path(Path): The location that the produced VM image should be copied
      to (on the local disk).
  """
  with api.step.nest('invoke tast') as presentation:
    tast_results_dir = api.path.mkdtemp(prefix='tast-results')
    tests = api.tast_exec.run_direct([_TAST_NAME], qcow_image_path,
                                     test_artifacts_dir, private_key_path,
                                     tast_results_dir,
                                     ['-var=pita.windowsLicensed=true'])

    try:
      src_path = tast_results_dir.join('tests').join(_TAST_NAME).join(
          'PvmDefault.zip')
      # TODO(meiring): Delete once the real process to generate a VM image is
      # available.
      api.step('create fake image', ['touch', src_path])

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
      failures, _ = api.tast_results.get_failures(result)
      is_empty = result.state.verdict == TaskState.VERDICT_UNSPECIFIED
      api.tast_results.print_results(failures, is_empty)

      raise api.step.StepFailure(
          'VM image build failed: {} failed'.format(_TAST_NAME))
    elif not image_exists:
      # Tast reports it has succeeded but the image could not be found.
      raise api.step.StepFailure(
          'VM image build failed: {} passed but image could not be found'
          .format(_TAST_NAME))


def commit_pin_uprev(api, properties, package, new_version_pin):
  """Commits and uploads the uprev of the version-pin file.

  Args:
    package (chromiumos.PackageInfo): the package to include in the
        commit message.
    new_version_pin (VersionPin): the new version pin data.
  """
  with api.step.nest('update VERSION-PIN') as presentation:
    with api.cros_source.checkout_overlays_context():
      api.cros_source.ensure_synced_cache()
      set_version_pin(api, properties, new_version_pin)

      message = '{}: updating version pin to latest - {}'.format(
          package.package_name, new_version_pin.version)

      version_path = get_version_path(api, properties)
      package_path = api.path.dirname(version_path)

      with api.step.nest('commit uprev'), \
            api.context(cwd=api.path.abs_to_path(package_path)):
        project = api.repo.project_info(project=api.git.repository_root())
        api.repo.start('uprev-parallels-pin', projects=[project.name])

        api.git.add([version_path])
        api.git.commit(message)

      with api.step.nest('upload CL to gerrit'):
        change = api.gerrit.create_change(project=project.name,
                                          topic=properties.topic)
        labels = {
            api.gerrit.Label.BOT_COMMIT: 1,
            api.gerrit.Label.COMMIT_QUEUE: 2,
        }
        api.gerrit.set_change_labels(change, labels)

        presentation.links['uploaded CL'] = api.gerrit.parse_gerrit_change_url(
            change)


def get_upstream_version(api, properties):
  """Gets the latest version of Parallels from the upstream bucket.

  Returns:
    string: the latest upstream version of Parallels.
  """
  with api.step.nest('find latest upstream version') as presentation:
    presentation.links['upstream directory'] = '{}/{}/{}'.format(
        _PANTHEON_PREFIX, properties.upstream_gs_bucket,
        properties.upstream_gs_path)

    gs_path = 'gs://{}/{}'.format(properties.upstream_gs_bucket,
                                  properties.upstream_gs_path)
    files = api.gsutil.list(
        gs_path, stdout=api.raw_io.output(),
        step_test_data=lambda: api.raw_io.test_api.stream_output(
            'gs://chromeos-binaries/some-path/parallels-desktop-1.0.0.9000.tbz2\n'
            'gs://chromeos-binaries/some-path/random-file.txt\n'
            'gs://chromeos-binaries/some-path/parallels-desktop-1.0.1.812.tbz2\n'
            'gs://chromeos-binaries/some-path/parallels-desktop-1.0.1.1098.tbz2\n'
            'gs://chromeos-binaries/some-path/parallels-desktop-1.0.1.100.tbz2\n'
        ))
    versions = []
    for filepath in files.stdout.splitlines():
      match = re.match(r'.*-([0-9]+(\.[0-9]+)+)\.tbz2', filepath)
      if match is None:
        continue
      # parse version into list[int]
      version_parts = map(int, match.group(1).split('.'))
      versions.append(version_parts)

    if len(versions) == 0:
      raise StepFailure('Upstream repository has no files matching pattern.')

    # Sort lexicographically, in descending order.
    versions.sort(reverse=True)
    result = ".".join(map(str, versions[0]))
    presentation.step_text = 'found version: {}'.format(result)
    return result


def get_version_pin(api, properties):
  """Reads and returns the content of the VERSION-PIN file.

  Before calling this function, ensure a synced version of the source must
  have been checked out.

  Returns:
    VersionPin: the pinned version data."""
  with api.step.nest('read pinned version file') as presentation:
    version_path = get_version_path(api, properties)
    json = api.file.read_json(
        name='VERSION-PIN', source=version_path, test_data={
            'version': '1.0.1.1000',
            'test_image': {
                'opaque': 'data'
            }
        })
    result = VersionPin(json['version'], json['test_image'])
    presentation.step_text = 'pinned version: {}'.format(result.version)
    return result


def set_version_pin(api, properties, new_version):
  """Sets the content of the VERSION-PIN file.

  Before calling this function, ensure a synced version of the source must
  have been checked out.

  Args:
    new_version(VersionPin): the new version pin data."""
  with api.step.nest('write pinned version file'):
    version_path = get_version_path(api, properties)
    api.file.write_json(
        name='VERSION-PIN', dest=version_path, data={
            'version': new_version.version,
            'test_image': new_version.test_image
        }, indent=2)


def get_version_path(api, properties):
  """Gets the path of the VERSION-PIN file."""
  return api.cros_source.workspace_path.join(properties.version_file)


def is_version_after(version, previous_version):
  """Returns if version occurs logically after pervious_version.

  For example, is_version_after('1.0.3.1', '1.0.2.2') returns true.

  Args:
    version(str): The version to compare.
    previous_version(str): The previous version to compare with.
  """
  parts = map(int, version.split('.'))
  previous_parts = map(int, previous_version.split('.'))
  # list comparison performs lexicographic comparison.
  return parts > previous_parts


def GenTests(api):
  good_props = {
      'package_info': {
          'category': 'app-emulation',
          'package_name': 'parallels-desktop'
      },
      'upstream_gs_bucket':
          'chromeos-binaries',
      'upstream_gs_path':
          'HOME/bcs-pita-private/project-pita-private/app-emulation/parallels-desktop/',
      'test_image_gs_bucket':
          'chromeos-test-assets-private',
      'test_image_gs_path':
          'tast/pita/pita',
      'version_file':
          'src/private-overlays/chromeos-partner-overlay/app-emulation/parallels-desktop/VERSION-PIN',
      'user_acls': ['owner@google.com:OWNER', 'reader@google.com:READ'],
      'group_acls': ['aclgroup@google.com:READ']
  }

  props = good_props.copy()
  del props['package_info']
  # Test missing recipe parameters.
  yield api.build_menu.test(
      'no-package', api.properties(**props),
      api.post_check(post_process.DoesNotRun, 'update VERSION-PIN'),
      api.post_check(post_process.StatusAnyFailure),
      api.expect_exception('ValueError'))

  props = good_props.copy()
  del props['upstream_gs_bucket']
  yield api.build_menu.test(
      'no-upstream-bucket', api.properties(**props),
      api.post_check(post_process.DoesNotRun, 'update VERSION-PIN'),
      api.post_check(post_process.StatusAnyFailure),
      api.expect_exception('ValueError'))

  props = good_props.copy()
  del props['upstream_gs_path']
  yield api.build_menu.test(
      'no-upstream-path', api.properties(**props),
      api.post_check(post_process.DoesNotRun, 'update VERSION-PIN'),
      api.post_check(post_process.StatusAnyFailure),
      api.expect_exception('ValueError'))

  props = good_props.copy()
  del props['version_file']
  yield api.build_menu.test(
      'no-version-file', api.properties(**props),
      api.post_check(post_process.DoesNotRun, 'update VERSION-PIN'),
      api.post_check(post_process.StatusAnyFailure),
      api.expect_exception('ValueError'))

  props = good_props.copy()
  del props['test_image_gs_bucket']
  yield api.build_menu.test(
      'no-test-image-bucket', api.properties(**props),
      api.post_check(post_process.DoesNotRun, 'update VERSION-PIN'),
      api.post_check(post_process.StatusAnyFailure),
      api.expect_exception('ValueError'))

  props = good_props.copy()
  del props['test_image_gs_path']
  yield api.build_menu.test(
      'no-test-image-path', api.properties(**props),
      api.post_check(post_process.DoesNotRun, 'update VERSION-PIN'),
      api.post_check(post_process.StatusAnyFailure),
      api.expect_exception('ValueError'))

  # Upstream version cannot be found.
  yield api.build_menu.test(
      'no-upstream-version', api.properties(**good_props),
      api.step_data('find latest upstream version.gsutil list',
                    stdout=api.raw_io.output('')),
      api.post_check(post_process.DoesNotRun, 'update VERSION-PIN'),
      api.post_check(post_process.StatusAnyFailure))

  # Upstream version is the same as in Chrome OS (nothing to do).
  yield api.build_menu.test(
      'uprev-not-required', api.properties(**good_props),
      api.post_check(post_process.DoesNotRun, 'update VERSION-PIN'),
      api.step_data(
          _BUILD_STEP_NAME + '.read pinned version file.VERSION-PIN',
          api.file.read_json({
              'version': '1.0.1.1098',
              'test_image': {
                  'opaque': 'data'
              }
          })))

  # Various build errors
  yield api.build_menu.test(
      'install-packages-fail', api.properties(**good_props),
      api.git.diff_check(True),
      api.post_check(post_process.DoesNotRun,
                     _BUILD_STEP_NAME + '.build images'),
      api.post_check(post_process.DoesNotRun,
                     _BUILD_STEP_NAME + '.run ebuild tests'),
      api.post_check(post_process.MustRun,
                     _BUILD_STEP_NAME + '.upload artifacts'),
      api.post_check(post_process.DoesNotRun,
                     _BUILD_STEP_NAME + '.upload artifacts.publish artifacts'),
      api.post_check(post_process.DoesNotRun, 'update VERSION-PIN'),
      api.post_check(post_process.StatusFailure),
      api.build_menu.set_build_api_return(
          _BUILD_STEP_NAME + '.install packages',
          'SysrootService/InstallPackages', retcode=1))

  yield api.build_menu.test(
      'bundle-fail', api.properties(**good_props), api.git.diff_check(True),
      api.post_check(post_process.MustRun, _BUILD_STEP_NAME + '.build images'),
      api.post_check(post_process.MustRun,
                     _BUILD_STEP_NAME + '.run ebuild tests'),
      api.post_check(post_process.MustRun,
                     _BUILD_STEP_NAME + '.upload artifacts'),
      api.post_check(post_process.DoesNotRun, 'update VERSION-PIN'),
      api.post_check(post_process.StatusAnyFailure),
      api.build_menu.set_build_api_return(
          _BUILD_STEP_NAME + '.upload artifacts',
          'ArtifactsService/BundleArtifacts', retcode=1))

  yield api.build_menu.test(
      'install-packages-and-bundle-fail', api.properties(**good_props),
      api.git.diff_check(True),
      api.post_check(post_process.DoesNotRun,
                     _BUILD_STEP_NAME + '.build images'),
      api.post_check(post_process.DoesNotRun,
                     _BUILD_STEP_NAME + '.run ebuild tests'),
      api.post_check(post_process.MustRun,
                     _BUILD_STEP_NAME + '.upload artifacts'),
      api.post_check(post_process.DoesNotRun, 'update VERSION-PIN'),
      api.post_check(post_process.StatusAnyFailure),
      api.build_menu.set_build_api_return(
          _BUILD_STEP_NAME + '.install packages',
          'SysrootService/InstallPackages', retcode=1),
      api.build_menu.set_build_api_return(
          _BUILD_STEP_NAME + '.upload artifacts',
          'ArtifactsService/BundleArtifacts', retcode=1))

  failureJson = json.loads("""[{
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
        "reason": "Lost SSH connection to VM"
      }
    ],
    "start": "2020-01-27T15:16:15.146771555-08:00",
    "end": "2020-01-27T15:16:33.420622341-08:00",
    "outDir": "/tmp/vm-test-results.JxZdcJ/tests/pita.CreateFromIso.uprev",
    "skipReason": ""
  }]""")

  # Tast fails
  yield api.build_menu.test(
      'tast-failure',
      api.properties(**good_props),
      api.git.diff_check(True),
      api.step_data(
          _IMAGE_STEP_NAME +
          '.invoke tast.process tast output.read results.json',
          api.file.read_json(failureJson)),
      api.post_check(post_process.StatusFailure),
      api.post_check(post_process.DoesNotRun,
                     _IMAGE_STEP_NAME + '.upload image'),
      api.post_check(post_process.DoesNotRun, 'update VERSION-PIN'),
  )

  successJson = json.loads("""[{
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
  }]""")

  # Tast appears to succeed, but not VM image was produced.
  yield api.build_menu.test(
      'tast-no-image', api.properties(**good_props), api.git.diff_check(True),
      api.step_data(
          _IMAGE_STEP_NAME +
          '.invoke tast.process tast output.read results.json',
          api.file.read_json(successJson)),
      api.step_data(_IMAGE_STEP_NAME + '.invoke tast.rename VM image',
                    retcode=1), api.post_check(post_process.StatusFailure),
      api.post_check(post_process.DoesNotRun,
                     _IMAGE_STEP_NAME + '.upload image'),
      api.post_check(post_process.DoesNotRun, 'update VERSION-PIN'))

  # Success
  yield api.build_menu.test(
      'uprev-success', api.properties(**good_props), api.git.diff_check(True),
      api.step_data(
          _IMAGE_STEP_NAME +
          '.invoke tast.process tast output.read results.json',
          api.file.read_json(successJson)),
      api.post_check(post_process.MustRun, _BUILD_STEP_NAME + '.build images'),
      api.post_check(post_process.MustRun,
                     _BUILD_STEP_NAME + '.run ebuild tests'),
      api.post_check(post_process.MustRun,
                     _BUILD_STEP_NAME + '.upload artifacts'),
      api.post_check(post_process.MustRun, _IMAGE_STEP_NAME + '.upload image'),
      api.post_check(post_process.MustRun, 'update VERSION-PIN'),
      api.post_check(post_process.StatusSuccess))
