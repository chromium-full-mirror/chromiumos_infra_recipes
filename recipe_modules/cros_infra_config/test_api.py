# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api
from google.protobuf import json_format as jsonpb

from PB.chromiumos.bot_scaling import BotPolicyCfg
from PB.chromiumos.builder_config import BuilderConfigs
from PB.chromiumos.dut_tracking import TrackingPolicyCfg
from PB.testplans.test_retry import SuiteRetryCfg


class CrosInfraConfigTestApi(recipe_test_api.RecipeTestApi):
  """Helpers for testing the infra_config module."""

  # Number of seconds to wait on gitiles file download.
  gitiles_timeout_seconds = 3 * 60

  def builder_configs_step_test_data(self):
    """A fn that can be passed to step_test_data to generate BuilderConfigs."""
    builder_configs = """
      {
        "builderConfigs": [
          {
            "id": {
              "name": "amd64-generic-postsubmit",
              "branch": "master",
              "type": "POSTSUBMIT"
            },
            "general": {
              "critical": true
            },
            "artifacts": {
              "prebuilts": "PRIVATE",
              "artifactsInfo": {
                "legacy": {
                  "outputArtifacts": [
                    {
                      "artifactTypes": ["IMAGE_ZIP"]
                    }
                  ]
                }
              },
              "artifactsGsBucket": "chromeos-image-archive",
              "prebuiltsGsBucket": "chromeos-prebuilt"
            },
            "chrome": {
              "internal": true
            },
            "build": {
              "portageProfile": {
                "profile": "generic_build"
              },
              "buildImages": {
                "imageTypes": ["BASE", "TEST"]
              },
              "installPackages": {
                "runSpec": "RUN"
              },
              "useFlags": [{"flag": "chrome_internal"}]
            },
            "unitTests": {
              "packageBlacklist": [],
              "ebuildsRunSpec": "RUN"
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
              "artifactsInfo": {
                "legacy": {
                  "outputArtifacts": [
                    {
                      "artifactTypes": ["IMAGE_ZIP"]
                    }
                  ]
                }
              }
            },
            "chrome": {
              "internal": true
            },
            "build": {
              "applyGerritChanges": true,
              "installPackages": {
                "runSpec": "RUN"
              },
              "useFlags": [{"flag": "chrome_internal"}]
            },
            "unitTests": {
              "packageBlacklist": [{
                "packageName": "chromite",
                "category": "chromeos-base",
                "version": ""
              }],
              "ebuildsRunSpec": "RUN"
            }
          },
          {
            "id": {
              "name": "staging-amd64-generic-cq",
              "branch": "master",
              "type": "CQ"
            },
            "general": {
              "critical": false,
              "environment": "STAGING",
              "sdkCacheVersion": "2"
            },
            "artifacts": {
              "prebuilts": "NONE",
              "artifactsInfo": {
                "legacy": {
                  "outputArtifacts": [
                    {
                      "artifactTypes": ["IMAGE_ZIP"]
                    }
                  ]
                }
              }
            },
            "chrome": {
              "internal": true
            },
            "build": {
              "applyGerritChanges": true,
              "useFlags": [{"flag": "chrome_internal"}],
              "installPackages": {
                "runSpec": "RUN"
              }
            },
            "unitTests": {
              "packageBlacklist": [{
                "packageName": "chromite",
                "category": "chromeos-base",
                "version": ""
              }],
              "ebuildsRunSpec": "RUN"
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
              "artifactsInfo": {
                "legacy": {
                  "outputArtifacts": [
                    {
                      "artifactTypes": [
                        "IMAGE_ZIP",
                        "AUTOTEST_FILES",
                        "TAST_FILES",
                        "PINNED_GUEST_IMAGES",
                        "EBUILD_LOGS",
                        "TEST_UPDATE_PAYLOAD"
                      ]
                    }
                  ]
                }
              },
              "prebuiltsGsBucket": "chromeos-prebuilt",
              "artifactsGsBucket": "chromeos-image-archive"
            },
            "chrome": {
              "internal": false
            },
            "build": {
              "installPackages": {
                "runSpec": "RUN"
              },
              "installToolchain": {
                "compileSource": false
              },
              "applyGerritChanges": true
            },
            "unitTests": {
              "packageBlacklist": [
              ],
              "ebuildsRunSpec": "RUN",
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
              "installPackages": {
                "runSpec": "RUN"
              }
            },
            "unitTests": {
              "packageBlacklist": [{
                "packageName": "chromite",
                "category": "chromeos-base",
                "version": ""
              }],
              "ebuildsRunSpec": "RUN"
            }
          },
          {
            "id": {
              "name": "arm-generic-pointless-cq",
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
              "installPackages": {
                "runSpec": "RUN"
              }
            },
            "unitTests": {
              "packageBlacklist": [{
                "packageName": "chromite",
                "category": "chromeos-base",
                "version": ""
              }],
              "ebuildsRunSpec": "RUN"
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
              "installPackages": {
                "runSpec": "RUN"
              }
            },
            "unitTests": {
              "packageBlacklist": [{
                "packageName": "chromite",
                "category": "chromeos-base",
                "version": ""
              }],
              "ebuildsRunSpec": "RUN"
            }
          },
          {
            "id": {
              "name": "bisecting-orchestrator",
              "branch": "master",
              "type": "POSTSUBMIT"
            },
            "general": {
              "critical": true,
              "environment": "PRODUCTION",
              "runWhen": {
                "mode": "ALWAYS_RUN"
              }
            },
            "artifacts": {
              "prebuilts": "NONE"
            },
            "chrome": {
              "internal": true
            },
            "build": {
              "useFlags": [
                 {"flag": "chrome_internal"}
              ],
              "buildImages": {
                "imageTypes": [
                  "TEST",
                  "BASE"
                ]
              },
              "installPackages": {
                "runSpec": "RUN"
              }
            },
            "unitTests": {
              "ebuildsRunSpec": "RUN"
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
              "installPackages": {
                "runSpec": "RUN_EXIT"
              },
              "applyGerritChanges": false
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
              "installPackages": {
                "runSpec": "RUN"
              }
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
              "installPackages": {
                "runSpec": "RUN_EXIT",
                "packages": [{
                  "packageName": "chromeos-kernel",
                  "category": "syskernel",
                  "version": "4.19"
                }]
              }
            }
          },
          {
            "id": {
              "name": "atlas-cq",
              "branch": "master",
              "type": "CQ"
            },
            "general": {
              "critical": true,
              "brokenBefore": "2019-11-01T00:00:00Z"
            },
            "artifacts": {
              "prebuilts": "NONE",
              "artifactsInfo": {
                "legacy": {
                  "outputArtifacts": [
                    {
                      "artifactTypes": ["IMAGE_ZIP"]
                    }
                  ]
                }
              }
            },
            "chrome": {
              "internal": true
            },
            "build": {
              "installPackages": {
                "runSpec": "RUN"
              },
              "applyGerritChanges": true
            },
            "unitTests": {
              "packageBlacklist": [{
                "packageName": "chromite",
                "category": "chromeos-base",
                "version": ""
              }],
              "ebuildsRunSpec": "RUN"
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
              "installPackages": {
                "runSpec": "RUN"
              },
              "applyGerritChanges": false
            },
            "unitTests": {
              "ebuildsRunSpec": "NO_RUN"
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
              "installPackages": {
                "runSpec": "RUN"
              },
              "applyGerritChanges": false
            },
            "unitTests": {
              "ebuildsRunSpec": "NO_RUN"
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
              "installPackages": {
                "runSpec": "RUN"
              },
              "applyGerritChanges": false
            },
            "unitTests": {
              "ebuildsRunSpec": "RUN_EXIT"
            }
          },
          {
            "id": {
              "name": "toolchain-orchestrator",
              "branch": "master",
              "type": "TOOLCHAIN"
            },
            "general": {
              "critical": true
            },
            "orchestrator": {
              "child_specs": [
              ],
              "gitilesCommit": {
                "host": "chrome-internal",
                "project": "chromeos/manifest-internal",
                "ref": "refs/heads/snapshot"
              },
              "gerritChanges": [{
                "host": "chromium-review.googlesource.com",
                "project": "chromiumos/overlays/chromiumos-overlay",
                "change": 1394249,
                "patchset": -1
              }]
            }
          },
          {
            "id": {
              "name": "clang-tidy-toolchain",
              "branch": "master",
              "type": "TOOLCHAIN"
            },
            "general": {
              "critical": false,
              "environment": "PRODUCTION",
              "runWhen": {
                "mode": "ALWAYS_RUN"
              }
            },
            "artifacts": {
              "prebuilts": "NONE",
              "artifactsGsBucket": "chromeos-image-archive",
              "artifactsInfo": {
                "legacy": {
                  "outputArtifacts": [
                    {
                      "artifactTypes": [
                        "EBUILD_LOGS"
                      ]
                    }
                  ]
                },
                "toolchain": {
                  "inputArtifacts": [
                    {
                      "artifactTypes": [
                        "CHROME_CLANG_WARNINGS_FILE"
                      ],
                      "gsLocations": [
                        "chromeos-toolchain-artifacts/clang-tidy-1"
                      ]
                    }
                  ],
                  "outputArtifacts": [
                    {
                      "artifactTypes": [
                        "CHROME_CLANG_WARNINGS_FILE"
                      ],
                      "gsLocations": [
                        "chromeos-toolchain-artifacts/clang-tidy-1"
                      ]
                    }
                  ]
                }
              }
            },
            "chrome": {
              "internal": true
            },
            "build": {
              "applyGerritChanges": true,
              "useFlags": [
                {"flag": "chrome_internal"},
                {"flag": "-cros-debug"},
                {"flag": "strict_toolchain_checks"},
                {"flag": "-afdo_use"},
                {"flag": "thinlto"},
                {"flag": "clang_tidy"}
              ],
              "installPackages": {
                "runSpec": "RUN",
                "compileSource": true,
                "packages": [
                  {
                    "packageName": "chromeos-chrome",
                    "category": "chromeos-base"
                  }
                ],
                "disableGoma": true
              }
            },
            "unitTests": {
              "ebuildsRunSpec": "NO_RUN"
            }
          },
          {
            "id": {
              "name": "orderfile-generate-orchestrator",
              "branch": "master",
              "type": "TOOLCHAIN"
            },
            "general": {
              "critical": true
            },
            "orchestrator": {
              "child_specs": [
                {"name": "orderfile-generate-toolchain"}
              ],
              "followOnOrchestrator": {
                "name": "orderfile-verify-orchestrator",
                "awaitCompletion": true
              },
              "gitilesCommit": {
                "host": "chrome-internal",
                "project": "chromeos/manifest-internal",
                "ref": "refs/heads/snapshot"
              },
              "gerritChanges": [{
                "host": "chromium-review.googlesource.com",
                "project": "chromiumos/overlays/chromiumos-overlay",
                "change": 1394249,
                "patchset": -1
              }]
            }
          },
          {
            "id": {
              "name": "benchmark-afdo-process",
              "branch": "master",
              "type": "TOOLCHAIN"
            },
            "general": {
              "critical": true,
              "environment": "PRODUCTION",
              "runWhen": {
                "mode": "ALWAYS_RUN"
              }
            },
            "artifacts": {
              "prebuilts": "NONE",
              "artifactsGsBucket": "chromeos-image-archive",
              "artifactsInfo": {
                "toolchain": {
                  "inputArtifacts": [
                    {
                      "artifactTypes": [
                        "UNVERIFIED_CHROME_BENCHMARK_PERF_FILE"
                      ],
                      "gsLocations": [
                        "chromeos-toolchain-artifacts/afdo/unvetted/benchmark",
                        "chromeos-prebuilt/afdo-job/llvm"
                      ]
                    },
                    {
                      "artifactTypes": [
                        "UNVERIFIED_CHROME_BENCHMARK_AFDO_FILE"
                      ],
                      "gsLocations": [
                        "chromeos-toolchain-artifacts/afdo/unvetted/benchmark",
                        "chromeos-prebuilt/afdo-job/llvm"
                      ]
                    }
                  ],
                  "outputArtifacts": [
                    {
                      "artifactTypes": [
                        "UNVERIFIED_CHROME_BENCHMARK_AFDO_FILE"
                      ],
                      "gsLocations": [
                        "chromeos-toolchain-artifacts/afdo/unvetted/benchmark",
                        "chromeos-prebuilt/afdo-job/llvm"
                      ],
                      "aclName": "public-read"
                    }
                  ]
                },
                "profileInfo": {
                  "afdoRelease": {"chromeCwpProfile": "silvermont"}
                }
              }
            },
            "chrome": {
              "internal": true
            },
            "build": {
              "applyGerritChanges": true,
              "useFlags": [
                {"flag": "chrome_internal"}
              ],
              "installPackages": {
                "compileSource": true,
                "runSpec": "RUN"
              }
            },
            "unitTests": {
              "ebuildsRunSpec": "RUN"
            }
          },
          {
            "id": {
              "name": "atlas-llvm-next",
              "branch": "master",
              "type": "TOOLCHAIN"
            },
            "general": {
              "critical": true,
              "environment": "PRODUCTION",
              "runWhen": {
                "mode": "ALWAYS_RUN"
              }
            },
            "artifacts": {
              "prebuilts": "NONE",
              "artifactsGsBucket": "chromeos-image-archive"
            },
            "chrome": {
              "internal": true
            },
            "build": {
              "applyGerritChanges": true,
              "useFlags": [
                {"flag": "chrome_internal"},
                {"flag": "-cros-debug"},
                {"flag": "strict_toolchain_checks"},
                {"flag": "llvm-next"},
                {"flag": "thinlto"}
              ],
              "sdkUpdate": {
                "compileSource": true
              },
              "installToolchain": {
                "compileSource": true
              },
              "installPackages": {
                "runSpec" : "RUN",
                "compileSource": true
              },
              "buildImages": {
                "imageTypes": [
                  "TEST",
                  "BASE"
                ]
              }
            },
            "unitTests": {
              "ebuildsRunSpec": "RUN"
            }
          },
          {
            "id": {
              "name": "orderfile-generate-toolchain",
              "branch": "master",
              "type": "TOOLCHAIN"
            },
            "general": {
              "critical": true,
              "environment": "PRODUCTION",
              "runWhen": {"mode": "ALWAYS_RUN"}
            },
            "artifacts": {
              "prebuilts": "NONE",
              "artifactsGsBucket": "chromeos-image-archive",
              "artifactsInfo": {
                "legacy": {
                  "outputArtifacts": [
                    {
                      "artifactTypes": [
                        "EBUILD_LOGS"
                      ]
                    }
                  ]
                },
                "toolchain": {
                  "inputArtifacts": [
                    {
                      "artifactTypes": [
                        "UNVERIFIED_CHROME_LLVM_ORDERFILE"
                      ],
                      "gsLocations": [
                        "chromeos-toolchain-artifacts/orderfile/unvetted",
                        "chromeos-prebuilt/afdo-job/orderfiles/unvetted"
                      ]
                    }
                  ],
                  "outputArtifacts": [
                    {
                      "artifactTypes": [
                        "UNVERIFIED_CHROME_LLVM_ORDERFILE"
                      ],
                      "gsLocations": [
                        "chromeos-toolchain-artifacts/orderfile/unvetted",
                        "chromeos-prebuilt/afdo-job/orderfiles/unvetted"
                      ]
                    }
                  ]
                },
                "profileInfo": {
                  "chromeCwpProfile": "silvermont"
                }
              }
            },
            "chrome": {"internal": true},
            "build": {
              "useFlags": [
                {"flag": "chrome_internal"},
                {"flag": "-cros-debug"},
                {"flag": "strict_toolchain_checks"},
                {"flag": "-orderfile_use"},
                {"flag": "orderfile_generate"},
                {"flag": "-strict_toolchain_checks"}
              ],
              "applyGerritChanges": true,
              "prepareForBuild": {
                "additionalArgs": {"chromeCwpProfile": "silvermont"}
              },
              "installPackages": {
                "compileSource": true,
                "runSpec": "RUN",
                "packages": [
                  {
                    "packageName": "chromeos-chrome",
                    "category": "chromeos-base"
                  }
                ]
              }
            },
            "unitTests": {"ebuildsRunSpec": "NO_RUN"}
          },
          {
            "id": {
              "name": "orderfile-verify-toolchain",
              "branch": "master",
              "type": "TOOLCHAIN"
            },
            "general": {
              "critical": true,
              "environment": "PRODUCTION",
              "runWhen": {
                "mode": "ALWAYS_RUN"
              }
            },
            "artifacts": {
              "prebuilts": "NONE",
              "artifactsGsBucket": "chromeos-image-archive",
              "artifactsInfo": {
                "legacy": {
                  "outputArtifacts": [
                    {
                      "artifactTypes": [
                        "EBUILD_LOGS"
                      ]
                    }
                  ]
                },
                "toolchain": {
                  "inputArtifacts": [
                    {
                      "artifactTypes": [
                        "UNVERIFIED_CHROME_LLVM_ORDERFILE"
                      ],
                      "gsLocations": [
                        "chromeos-toolchain-artifacts/orderfile/unvetted",
                        "chromeos-prebuilt/afdo-job/orderfiles/unvetted"
                      ]
                    },
                    {
                      "artifactTypes": [
                        "VERIFIED_CHROME_LLVM_ORDERFILE"
                      ],
                      "gsLocations": [
                        "chromeos-toolchain-artifacts/orderfile/vetted",
                        "chromeos-prebuilt/afdo-job/orderfiles/vetted"
                      ]
                    }
                  ],
                  "outputArtifacts": [
                    {
                      "artifactTypes": [
                        "VERIFIED_CHROME_LLVM_ORDERFILE"
                      ],
                      "gsLocations": [
                        "chromeos-toolchain-artifacts/orderfile/vetted",
                        "chromeos-prebuilt/afdo-job/orderfiles/vetted"
                      ],
                      "aclName": "public-read"
                    }
                  ]
                },
                "profileInfo": {"chromeCwpProfile": "silvermont"}
              }
            },
            "chrome": {
              "internal": true
            },
            "build": {
              "applyGerritChanges": true,
              "useFlags": [
                {"flag": "chrome_internal"},
                {"flag": "-cros-debug"},
                {"flag": "strict_toolchain_checks"},
                {"flag": "orderfile_verify"},
                {"flag": "-reorder_text_sections"}
              ],
              "prepareForBuild": {
                "additionalArgs": {"chromeCwpProfile": "silvermont"}
              },
              "installPackages": {
                "compileSource": true,
                "runSpec": "RUN",
                "packages": [
                  {
                    "packageName": "bash",
                    "category": "app-shells"
                  },
                  {
                    "packageName": "chromeos-chrome",
                    "category": "chromeos-base"
                  }
                ]
              }
            },
            "unitTests": {
              "ebuildsRunSpec": "RUN"
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
              "child_specs": [
                {"name": "amd64-generic-postsubmit"},
                {"name": "arm-generic-postsubmit"}
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
              "child_specs": [
                {"name": "amd64-generic-cq"},
                {"name": "arm-generic-cq"},
                {"name": "arm-generic-pointless-cq"},
                {"name": "atlas-cq"}
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
            },
            "build": {
              "applyGerritChanges": true
            }
          }
        ]
      }
    """
    configs = jsonpb.Parse(builder_configs, BuilderConfigs())

    # Humans can edit the string above for test data, impl reads binary proto.
    return self.m.depot_gitiles.make_encoded_file(configs.SerializeToString())

  def bot_policy_test_data(self):
    """A fn that can be passed to step_test_data to generate BotPolicies."""
    bot_policy_config = """
            {
            	"botPolicies": [
            		{
            			"botGroup": "cq",
            			"botType": {
            				"botSize": "large",
            				"coresPerBot": 32
            			},
            			"regionRestrictions": [
            				{
            					"region": "us-central1-b",
            					"prefix": "chromeos-ci-cq-us-central1-b-x32",
            					"weight": 0.245
            				},
            				{
            					"region": "us-central2-d",
            					"prefix": "chromeos-ci-cq-us-central2-d-x32",
            					"weight": 0.31
            				},
            				{
            					"region": "us-east1-d",
            					"prefix": "chromeos-ci-cq-us-east1-d-x32",
            					"weight": 0.245
            				},
            				{
            					"region": "us-west1-b",
            					"prefix": "chromeos-ci-cq-us-west1-b-x32",
            					"weight": 0.2
            				}
            			],
			            "swarmingDimensions": [
				              {
					                "name": "role",
					                "value": "cq",
                          "values": ["cq", "bar"]
				              },
				              {
					                "name": "bot_size",
					                "value": "large",
                          "values": ["large"]
				              }
			            ]
            		}
            	]
            }
          """
    configs = jsonpb.Parse(bot_policy_config, BotPolicyCfg())
    return self.m.depot_gitiles.make_encoded_file(configs.SerializeToString())

  def vm_retry_test_data(self):
    """A fn that can be passed to step_test_data to generate SuiteRetryCfg."""
    vm_retry_config = """
        {
        	"testSuite": "tast_vm",
        	"suiteScenarios": [
        		{
        			"testName": "arc.Boot",
        			"reason": "Lost SSH connection",
        			"verdict": "VERDICT_FAILED",
                                "requires_restart": true
        		},
        		{
        			"testName": "arc.Boot",
        			"reason": "Test did not finish",
        			"verdict": "VERDICT_FAILED"
        		}
        	]
        }
    """
    configs = jsonpb.Parse(vm_retry_config, SuiteRetryCfg())
    return self.m.depot_gitiles.make_encoded_file(configs.SerializeToString())

  def dut_tracking_test_data(self):
    """A fn that can be passed to step_test_data to generate TrackingPolicyCfg."""
    dut_tracking_config = """
        {
        	"policies": [
            		{
			            "name": "atlas",
			            "dimensions": [
			            	{
			            		"name": "label-board",
			            		"value": "atlas"
			            	}
			            ],
			            "modes": [
			            	"TASK_BOT_COUNT"
			            ],
			            "lookbackHours": -24
		            }
        	]
        }
    """
    configs = jsonpb.Parse(dut_tracking_config, TrackingPolicyCfg())
    return self.m.depot_gitiles.make_encoded_file(configs.SerializeToString())
