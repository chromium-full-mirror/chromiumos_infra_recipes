# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building a BuildTarget image for CQ."""

from PB.go.chromium.org.luci.buildbucket.proto import common
from PB.recipe_engine.result import RawResult

from recipe_engine import post_process
from recipe_engine.recipe_api import StepFailure

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/random',
    'recipe_engine/raw_io',
    'recipe_engine/runtime',
    'recipe_engine/step',
    'bot_scaling',
    'build_menu',
    'cros_infra_config',
    'cros_tags',
    'easy',
    'future_utils',
    'test_util',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):
  api.easy.log_parent_step()

  if api.cros_infra_config.is_staging:
    api.bot_scaling.drop_cpu_cores(min_cpus_left=4, max_drop_ratio=.75)

  try:
    with api.build_menu.configure_builder() as config, \
        api.build_menu.setup_workspace_and_chroot() as is_relevant:
      if is_relevant:
        return DoRunSteps(api, config)
      return RawResult(status=common.SUCCESS,
                       summary_markdown='Build was not relevant.')
  finally:
    # If the parent build is cancelled, by default the child build will have an
    # INFRA_FAILURE status. Check if this build was cancelled because its
    # parent was cancelled, and set the status.
    parent = api.cros_tags.get_values('parent_buildbucket_id')
    if parent and api.runtime.in_global_shutdown:
      # pylint: disable=lost-exception
      return RawResult(
          status=common.CANCELED,
          summary_markdown='Parent orchestrator ({}) cancelled'.format(
              api.buildbucket.build_url(build_id=parent[0])))


def DoRunSteps(api, config):
  env_info = api.build_menu.setup_sysroot_and_determine_relevance()

  # TODO(b/205159611): Experiment doing relevancy checks via the Build API.
  if api.cros_infra_config.is_staging:
    api.build_menu.is_cq_build_relevant(env_info.packages,
                                        include_rev_deps=False)

  if env_info.pointless:
    return RawResult(status=common.SUCCESS,
                     summary_markdown='Build was pointless.')

  packages = env_info.packages

  failing_build_exception = None
  try:
    api.build_menu.bootstrap_sysroot(config)
    if api.build_menu.install_packages(config, packages):
      # Create the test containers async.
      test_containers_runner = api.future_utils.create_parallel_runner()
      test_containers_runner.run_function_async(
          lambda cfg, _: api.build_menu.create_containers(cfg), config)
      # TODO(b/253642578): Experiment running unit tests on only packages
      # which are affected by the CLs in the CQ run.
      if api.cros_infra_config.is_staging:
        api.build_menu.build_images(config)
        api.build_menu.run_unittests_cl_affected_deps(config)
        api.build_menu.unit_test_images(config)
      else:
        # We have no steps following build_and_test_images, so we don't need to
        # check the return value.
        api.build_menu.build_and_test_images(config)
      # Pause and throw if test containers failed to upload.
      test_containers_runner.wait_for_and_throw()
  except StepFailure as sf:
    # If we catch an exception, swallow it and store it so the next steps can
    # still occur (as stated above there is value in uploading the artifact even
    # in cases of build failure for debug purposes).
    failing_build_exception = sf

  # Always upload the artifacts, regardless of whether the above threw an
  # exception.
  try:
    api.build_menu.upload_artifacts(config)
  except StepFailure as sf:
    # If uploading artifacts threw an exception, surface that exception unless
    # build_and_test_images above threw an exception, in which case we want to
    # surface *that* exception for accuracy in reporting the build (and it's
    # likely that upload artifacts failed as a result of those previous issues).
    raise failing_build_exception or sf

  # Finally, if there was an exception caught above in building the image, but
  # the upload succeeded, raise that exception.
  if failing_build_exception:
    raise failing_build_exception  # pylint: disable=raising-bad-type
  return None


def GenTests(api):

  # Normal CQ build, with one gerrit_change.
  yield api.build_menu.test(
      'cq-build', api.post_check(post_process.MustRun, 'build images'),
      api.post_check(post_process.MustRun, 'run ebuild tests'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.post_check(post_process.DoesNotRun,
                     'upload artifacts.publish artifacts'),
      api.post_check(post_process.StatusSuccess), cq=True, build_target='coral')

  # This covers the Relevance check.
  yield api.build_menu.test(
      'prepare-for-build-pointless',
      api.post_check(post_process.DoesNotRun, 'build images'),
      api.post_check(post_process.DoesNotRun, 'run ebuild tests'),
      api.post_check(post_process.DoesNotRun, 'upload artifacts'),
      api.post_check(post_process.DoesNotRun,
                     'upload artifacts.publish artifacts'),
      api.post_check(post_process.StatusSuccess), cq=True, build_target='coral',
      input_properties=api.test_util.build_menu_properties(artifact_build=True),
      artifact_pointless=True)

  # This covers the env_info.pointless check.
  yield api.build_menu.test(
      'pointless-cq-build',
      api.post_check(post_process.DoesNotRun, 'build images'),
      api.post_check(post_process.DoesNotRun, 'run ebuild tests'),
      api.post_check(post_process.DoesNotRun, 'upload artifacts'),
      api.post_check(post_process.DoesNotRun,
                     'upload artifacts.publish artifacts'),
      api.post_check(post_process.StatusSuccess), cq=True,
      build_target='staging-amd64-generic', pointless=True)

  # CQ build with install-packages failure.
  yield api.build_menu.test(
      'install-packages-fail',
      api.post_check(post_process.DoesNotRun, 'build images'),
      api.post_check(post_process.DoesNotRun, 'run ebuild tests'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.post_check(post_process.DoesNotRun,
                     'upload artifacts.publish artifacts'),
      api.post_check(post_process.StatusFailure),
      api.build_menu.set_build_api_return(
          'install packages', endpoint='SysrootService/InstallPackages',
          retcode=2,
          data='{ "failed_package_data": [{"name": {"package_name": "bar", "category": "foo", "version": "1.0-r1"}, "log_path": {"path": "/all/your/package/foo:bar-1.0-r1"}}] }'
      ), build_target='coral', cq=True)


  # CQ build with artifact bundling failure.
  yield api.build_menu.test(
      'bundle-fail', api.post_check(post_process.MustRun, 'build images'),
      api.post_check(post_process.MustRun, 'run ebuild tests'),
      api.post_check(post_process.StatusAnyFailure),
      api.build_menu.set_build_api_return(
          'upload artifacts.call artifacts service', 'ArtifactsService/Get',
          retcode=1), cq=True, build_target='coral')

  # CQ build with failures in install packages and bundle artifacts.
  yield api.build_menu.test(
      'install-packages-and-bundle-fail',
      api.post_check(post_process.DoesNotRun, 'build images'),
      api.post_check(post_process.DoesNotRun, 'run ebuild tests'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.post_check(post_process.StatusFailure),
      api.build_menu.set_build_api_return('install packages',
                                          'SysrootService/InstallPackages',
                                          retcode=1),
      api.build_menu.set_build_api_return(
          'upload artifacts.call artifacts service', 'ArtifactsService/Get',
          retcode=1), cq=True, build_target='coral')

  yield api.build_menu.test(
      'parent-cancelled',
      api.runtime.global_shutdown_on_step(
          'configure builder.gitiles-fetch-ref'),
      api.post_check(
          post_process.ResultReason,
          'Parent orchestrator (https://cr-buildbucket.appspot.com/build/123) cancelled'
      ),
      api.post_process(post_process.StatusException),
      api.post_process(post_process.DropExpectation),
      tags=api.cros_tags.tags(parent_buildbucket_id='123'),
      cq=True,
      build_target='coral',
  )

  # This covers any staging-specific logic.
  yield api.build_menu.test(
      'staging-cq-build',
      api.post_check(post_process.MustRun, 'build images'),
      api.post_check(post_process.MustRun, 'run ebuild tests'),
      # TODO(b/253642578): Remove check when experiment is done.
      api.post_check(post_process.MustRun,
                     'run ebuild tests for cl affected packages'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.post_check(post_process.DoesNotRun,
                     'upload artifacts.publish artifacts'),
      api.post_check(post_process.StatusSuccess),
      cq=True,
      build_target='staging-amd64-generic',
      pointless=False)
