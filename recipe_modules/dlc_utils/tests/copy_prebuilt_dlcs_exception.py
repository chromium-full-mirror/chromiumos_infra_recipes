# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.chromite.api.sysroot import Sysroot
from PB.chromiumos.common import BuildTarget, Chroot
from recipe_engine import post_process
from recipe_engine.recipe_api import StepFailure

DEPS = [
    'recipe_engine/assertions',
    'cros_build_api',
    'dlc_utils',
]



def RunSteps(api):
  with api.assertions.assertRaises(StepFailure):
    api.dlc_utils.copy_prebuilt_dlcs(
        'bucket',
        Sysroot(path='/build/target', build_target=BuildTarget(name='target')),
        Chroot(),
        False,
    )


def GenTests(api):

  yield api.test(
      'duplicate-hashes',
      api.cros_build_api.set_api_return(
          parent_step_name='upload prebuilt DLCs',
          endpoint='DlcService/GenerateDlcArtifactsList',
          data='''{"dlc_artifacts":[
  {
    "image_hash": "88d54cb6b5bba15a71ffda3ca75446eb453bf7fe393e3595d3bc52beb3b61711",
    "image_name": "dlc.img",
    "gs_uri_path": "gs://some/uri/prefix/for/dlc-1"
  },{
    "image_hash": "99d54cb6b5bba15a71ffda3ca75446eb453bf7fe393e3595d3bc52beb3b61711",
    "image_name": "dlc.img",
    "gs_uri_path": "gs://some/uri/prefix/for/dlc-1"
  }
  ]}''', retcode=0),
      api.post_process(post_process.DropExpectation),
  )
