# Copyright 2025 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for performing various operations against the online HSMs."""

from PB.chromite.api.signing import SignViaOnlineHsmRequest
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    "recipe_engine/properties",
    "recipe_engine/step",
    "cros_build_api",
    "git",
    "signing",
    "src_state",
]


def RunSteps(api: RecipeApi):

  with api.step.nest("set up dependencies"):
    api.git.clone(
        "https://chromium.googlesource.com/chromiumos/chromite/",
        target_path=api.src_state.workspace_path / "infra/chromite-HEAD",
        branch="main",
        single_branch=True,
    )

    api.git.clone(
        "https://chromium.googlesource.com/chromiumos/chromite/",
        target_path=api.src_state.workspace_path / "infra/chromite",
        branch="main",
        single_branch=True,
    )

  with api.step.nest("reach out to HSM"):
    api.step(
        "docker auth",
        [
            "gcloud",
            "auth",
            "configure-docker",
            "us-docker.pkg.dev",
        ],
    )
    api.step(
        "docker pull",
        [
            "docker",
            "pull",
            api.signing.signing_docker_image,
        ],
    )
    api.cros_build_api.SigningService.SignViaOnlineHsm(
        SignViaOnlineHsmRequest(docker_image=api.signing.signing_docker_image))


def GenTests(api: RecipeTestApi):
  yield api.test(
      "hsm-basic",
      api.post_check(
          post_process.StepCommandContains,
          "reach out to HSM.docker pull",
          [
              "docker",
              "pull",
              "us-docker.pkg.dev/chromeos-release-bot/signing/signing:latest:",
          ],
      ),
      api.post_check(
          post_process.LogContains,
          "reach out to HSM.call chromite.api.SigningService/SignViaOnlineHsm",
          "request",
          ["us-docker.pkg.dev/chromeos-release-bot/signing/signing:latest:"],
      ),
      api.post_check(
          post_process.MustRun,
          "reach out to HSM.call chromite.api.SigningService/SignViaOnlineHsm",
      ),
      api.post_process(post_process.DropExpectation),
  )
