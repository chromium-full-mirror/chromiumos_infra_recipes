# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.chromite.api.sysroot import Sysroot
from PB.chromiumos.common import BuildTarget, Chroot
from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'cros_build_api',
    'dlc_utils',
]



def RunSteps(api):
  dlcs = api.dlc_utils.copy_prebuilt_dlcs(
      'bucket',
      Sysroot(path='/build/target', build_target=BuildTarget(name='target')),
      Chroot(),
      api.properties['staging'],
  )
  if api.properties['no_response']:
    api.assertions.assertEqual({}, dlcs)
  else:
    staging = 'staging-' if api.properties['staging'] else 'prod-'
    api.assertions.assertEqual(
        {
            f'gs://bucket/{staging}dlc-images/uri/prefix/for/dlc-1/dlc.img': {
                'hash':
                    '88d54cb6b5bba15a71ffda3ca75446eb453bf7fe393e3595d3bc52beb3b61711',
                'id':
                    'dlc-1',
            },
            f'gs://bucket/{staging}dlc-images/uri/prefix/for/dlc-2/dlc.img': {
                'hash':
                    '99d54cb6b5bba15a71ffda3ca75446eb453bf7fe393e3595d3bc52beb3b61711',
                'id':
                    'dlc-2'
            }
        }, dlcs)


def GenTests(api):

  def OneOfTheStepsContains(check, step_odict, step, argument_sequence,
                            num_tries):
    """Checks if one of the invocations of a step contains the sequence.

    For steps in parallel, use this to check against any of the steps with the
    `(n)` suffixes.
    """
    total_checks = False
    for i in range(0, num_tries):
      suffix = '' if i == 0 else f' ({i + 1})'
      total_checks = total_checks or (argument_sequence
                                      in step_odict[f'{step}{suffix}'].cmd)
    check('command line for step %s contained %s' % (step, argument_sequence),
          total_checks)

  yield api.test(
      'basic',
      api.properties(staging=False, no_response=False),
      api.step_data('upload prebuilt DLCs.gcloud storage ls', retcode=1),
      api.step_data('upload prebuilt DLCs.gcloud storage ls (2)', retcode=1),
      api.post_check(OneOfTheStepsContains,
                     'upload prebuilt DLCs.gcloud storage cp', [
                         'gcloud', 'storage', 'cp', '--recursive',
                         '--no-clobber', 'gs://some/uri/prefix/for/dlc-1',
                         'gs://bucket/prod-dlc-images/uri/prefix/for/dlc-1'
                     ], 2),
      api.post_check(OneOfTheStepsContains,
                     'upload prebuilt DLCs.gcloud storage cp', [
                         'gcloud', 'storage', 'cp', '--recursive',
                         '--no-clobber', 'gs://some/uri/prefix/for/dlc-2',
                         'gs://bucket/prod-dlc-images/uri/prefix/for/dlc-2'
                     ], 2),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'staging',
      api.properties(staging=True, no_response=False),
      api.step_data('upload prebuilt DLCs.gcloud storage ls', retcode=1),
      api.step_data('upload prebuilt DLCs.gcloud storage ls (2)', retcode=1),
      api.post_check(OneOfTheStepsContains,
                     'upload prebuilt DLCs.gcloud storage cp', [
                         'gcloud', 'storage', 'cp', '--recursive',
                         '--no-clobber', 'gs://some/uri/prefix/for/dlc-1',
                         'gs://bucket/staging-dlc-images/uri/prefix/for/dlc-1'
                     ], 2),
      api.post_check(OneOfTheStepsContains,
                     'upload prebuilt DLCs.gcloud storage cp', [
                         'gcloud', 'storage', 'cp', '--recursive',
                         '--no-clobber', 'gs://some/uri/prefix/for/dlc-2',
                         'gs://bucket/staging-dlc-images/uri/prefix/for/dlc-2'
                     ], 2),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'files-exist',
      api.properties(staging=False, no_response=False),
      api.step_data('upload prebuilt DLCs.gcloud storage ls', retcode=0),
      api.step_data('upload prebuilt DLCs.gcloud storage ls (2)', retcode=0),
      api.post_process(post_process.DoesNotRun,
                       'upload prebuilt DLCs.gcloud storage cp'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'no-response',
      api.properties(staging=False, no_response=True),
      api.cros_build_api.set_api_return(
          parent_step_name='upload prebuilt DLCs',
          endpoint='DlcService/GenerateDlcArtifactsList', data='{}', retcode=0),
      api.post_process(post_process.DoesNotRun,
                       'upload prebuilt DLCs.gcloud storage cp'),
      api.post_process(post_process.DropExpectation),
  )
