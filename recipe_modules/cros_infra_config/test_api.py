# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api


class CrosInfraConfigTestApi(recipe_test_api.RecipeTestApi):
  """Helpers for testing the infra_config module."""

  # Number of seconds to wait on gitiles file download.
  gitiles_timeout_seconds = 3 * 60

  def builder_configs_step_test_data(self):
    """A fn that can be passed to step_test_data to generate BuilderConfigs.

    Note the field "newUnknownField", which tests the case where the proto in
    chromeos/infra/config is using a proto version newer than the one in this
    repo.
    """
    return self.m.gitiles.make_encoded_file("""
            {
              "builderConfigs": [
                {
                  "id": {
                    "name": "amd64-generic-postsubmit",
                    "branch": "master",
                    "type": "POSTSUBMIT",
                    "newUnknownField": "some-value"
                  },
                  "general": {
                    "critical": true
                  },
                  "artifacts": {
                    "prebuilts": "PRIVATE",
                    "artifact_types": ["IMAGE_ZIP"],
                    "artifacts_gs_bucket": "chromeos-image-archive",
                    "prebuilts_gs_bucket": "chromeos-prebuilt"
                  },
                  "chrome": {
                    "internal": true
                  },
                  "build": {
                    "portage_profile": {
                      "profile": "generic_build"
                    },
                    "image_types": ["TEST"],
                    "install_packages": "RUN"
                  },
                  "unit_tests": {
                    "package_blacklist": [],
                    "ebuilds_run_spec": "RUN"
                  }
                },
                {
                  "id": {
                    "name": "amd64-generic-cq",
                    "branch": "master",
                    "type": "CQ"
                  },
                  "general": {
                    "critical": true
                  },
                  "artifacts": {
                    "prebuilts": "NONE",
                    "artifact_types": ["IMAGE_ZIP"]
                  },
                  "chrome": {
                    "internal": true
                  },
                  "build": {
                    "install_packages": "RUN",
                    "apply_gerrit_changes": true
                  },
                  "unit_tests": {
                    "package_blacklist": [{
                      "package_name": "chromite",
                      "category": "chromeos-base",
                      "version": ""
                    }],
                    "ebuilds_run_spec": "RUN"
                  }
                },
                {
                  "id": {
                    "name": "amd64-generic-snapshot",
                    "branch": "master",
                    "type": "POSTSUBMIT"
                  },
                  "general": {
                    "critical": false
                  },
                  "artifacts": {
                    "prebuilts": "PUBLIC",
                    "artifact_types": [
                      "IMAGE_ZIP",
                      "AUTOTEST_FILES",
                      "TAST_FILES",
                      "PINNED_GUEST_IMAGES",
                      "EBUILD_LOGS",
                      "TEST_UPDATE_PAYLOAD"
                    ],
                    "prebuiltsGsBucket": "chromeos-prebuilt",
                    "artifactsGsBucket": "chromeos-image-archive"
                  },
                  "chrome": {
                    "internal": false
                  },
                  "build": {
                    "install_packages": "RUN",
                    "compile_tool_chain": false,
                    "apply_gerrit_changes": true
                  },
                  "unit_tests": {
                    "package_blacklist": [
                    ],
                    "ebuilds_run_spec": "RUN",
                    "emptySysroot": false
                  }
                },
                {
                  "id": {
                    "name": "arm-generic-cq",
                    "branch": "master",
                    "type": "CQ"
                  },
                  "general": {
                    "critical": false
                  },
                  "artifacts": {
                    "prebuilts": "NONE"
                  },
                  "chrome": {
                    "internal": true
                  },
                  "build": {
                    "install_packages": "RUN"
                  },
                  "unit_tests": {
                    "package_blacklist": [{
                      "package_name": "chromite",
                      "category": "chromeos-base",
                      "version": ""
                    }],
                    "ebuilds_run_spec": "RUN"
                  }
                },
                {
                  "id": {
                    "name": "staging-arm-generic-cq",
                    "branch": "master",
                    "type": "CQ"
                  },
                  "general": {
                    "critical": false,
                    "environment": "STAGING"
                  },
                  "artifacts": {
                    "prebuilts": "NONE"
                  },
                  "chrome": {
                    "internal": true
                  },
                  "build": {
                    "install_packages": "RUN"
                  },
                  "unit_tests": {
                    "package_blacklist": [{
                      "package_name": "chromite",
                      "category": "chromeos-base",
                      "version": ""
                    }],
                    "ebuilds_run_spec": "RUN"
                  }
                },
                {
                  "id": {
                    "name": "amd64-generic-bisect",
                    "branch": "master",
                    "type": "POSTSUBMIT"
                  },
                  "general": {
                    "critical": true
                  },
                  "chrome": {
                    "internal": true
                  },
                  "build": {
                    "install_packages": "RUN_EXIT",
                    "apply_gerrit_changes": false
                  }
                },
                {
                  "id": {
                    "name": "arm-generic-postsubmit",
                    "branch": "master",
                    "type": "POSTSUBMIT"
                  },
                  "general": {
                    "critical": false
                  },
                  "build": {
                    "install_packages": "RUN"
                  }
                },
                {
                  "id": {
                    "name": "arm-generic-v42-buildtest-postsubmit",
                    "branch": "master",
                    "type": "POSTSUBMIT"
                  },
                  "general": {
                    "critical": false
                  },
                  "build": {
                    "install_packages": "RUN_EXIT",
                    "packages": [{
                      "package_name": "chromeos-kernel",
                      "category": "syskernel",
                      "version": "4.19"
                    }]
                  }
                },
                {
                  "id": {
                    "name": "atlas-cq",
                    "branch": "master",
                    "type": "CQ"
                  },
                  "general": {
                    "critical": true
                  },
                  "artifacts": {
                    "prebuilts": "NONE",
                    "artifact_types": ["IMAGE_ZIP"]
                  },
                  "chrome": {
                    "internal": true
                  },
                  "build": {
                    "install_packages": "RUN",
                    "apply_gerrit_changes": true
                  },
                  "unit_tests": {
                    "package_blacklist": [{
                      "package_name": "chromite",
                      "category": "chromeos-base",
                      "version": ""
                    }],
                    "ebuilds_run_spec": "RUN"
                  }
                },
                {
                  "id": {
                    "name": "target-baseline",
                    "branch": "master",
                    "type": "CQ"
                  },
                  "general": {
                    "critical": false
                  },
                  "build": {
                    "install_packages": "RUN",
                    "apply_gerrit_changes": false
                  },
                  "unit_tests": {
                    "ebuilds_run_spec": "NO_RUN"
                  }
                },
                {
                  "id": {
                    "name": "grunt-postsubmit",
                    "branch": "master",
                    "type": "POSTSUBMIT"
                  },
                  "general": {
                    "critical": false
                  },
                  "build": {
                    "install_packages": "RUN",
                    "apply_gerrit_changes": false
                  },
                  "unit_tests": {
                    "ebuilds_run_spec": "NO_RUN"
                  }
                },
                {
                  "id": {
                    "name": "grunt-unittest-only-postsubmit",
                    "branch": "master",
                    "type": "POSTSUBMIT"
                  },
                  "general": {
                    "critical": false
                  },
                  "build": {
                    "install_packages": "RUN",
                    "apply_gerrit_changes": false
                  },
                  "unit_tests": {
                    "ebuilds_run_spec": "RUN_EXIT"
                  }
                },
                {
                  "id": {
                    "name": "postsubmit-orchestrator",
                    "branch": "master",
                    "type": "POSTSUBMIT"
                  },
                  "general": {
                    "critical": true
                  },
                  "orchestrator": {
                    "children": [
                      "amd64-generic-postsubmit",
                      "arm-generic-postsubmit"
                    ]
                  }
                },
                {
                  "id": {
                    "name": "cq-orchestrator",
                    "branch": "master",
                    "type": "CQ"
                  },
                  "general": {
                    "critical": true
                  },
                  "orchestrator": {
                    "children": [
                      "amd64-generic-cq",
                      "arm-generic-cq",
                      "atlas-cq"
                    ]
                  }
                },
                {
                  "id": {
                    "name": "chromite-cq",
                    "branch": "master",
                    "type": "CQ"
                  },
                  "general": {
                    "critical": true
                  }
                }
              ]
            }
          """)

  def test_config_file(self):
    """A step_test_data function to simulate test config download."""
    return self.m.gitiles.make_encoded_file("")
