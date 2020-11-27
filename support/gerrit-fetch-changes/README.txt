To test locally you'll need to authenticate with gerrit OAuth scopes:

luci-auth login -scopes 'https://www.googleapis.com/auth/userinfo.email https://www.googleapis.com/auth/gerritcodereview'


As of Dec 11, 2019 will return a json object like the following:
----------------------------------------------------------------

{
  "changes": [
    {
      "host": "chromium-review.googlesource.com",
      "change_number": 1919750,
      "patch_set": 1,
      "info": {
        "_number": 1919750,
        "id": "chromiumos%2Fthird_party%2Fkernel~chromeos-4.4~I0fc2b14fd6ea7553db57d39de366399880ed9d3c",
        "change_id": "I0fc2b14fd6ea7553db57d39de366399880ed9d3c",
        "project": "chromiumos/third_party/kernel",
        "branch": "chromeos-4.4",
        "topic": "",
        "hashtags": [
          "merge-v4.4.202"
        ],
        "subject": "CHROMIUM: Merge 'v4.4.202' into chromeos-4.4",
        "status": "MERGED",
        "created": "2019-11-17 01:50:32.000000000",
        "updated": "2019-11-19 15:17:13.000000000",
        "mergeable": false,
        "messages": null,
        "submitted": "2019-11-19 15:17:13.000000000",
        "submit_type": "",
        "insertions": 1017,
        "deletions": 68,
        "unresolved_comment_count": 0,
        "has_review_started": true,
        "owner": {
          "_account_id": 1146659
        },
        "labels": null,
        "submitter": {
          "_account_id": 1111084
        },
        "reviewers": {
          "CC": null,
          "REVIEWER": null,
          "REMOVED": null
        },
        "revert_of": 0,
        "current_revision": "bb52c7a3d9f0a28ad4dce5f8fc7fcdf92106b754",
        "revisions": null,
        "_more_changes": false
      },
      "patch_set_revision": "bb52c7a3d9f0a28ad4dce5f8fc7fcdf92106b754",
      "revision_info": {
        "_number": 1,
        "kind": "REWORK",
        "ref": "refs/changes/50/1919750/1",
        "uploader": {
          "_account_id": 1146659
        },
        "commit": {
          "author": {},
          "committer": {}
        },
        "files": {
          "/COMMIT_MSG": {
            "size_delta": 0,
            "size": 0
          },
          "/MERGE_LIST": {
            "size_delta": 0,
            "size": 0
          },
          "Documentation/ABI/testing/sysfs-devices-system-cpu": {
            "size_delta": 0,
            "size": 0
          },
          "Documentation/hw-vuln/tsx_async_abort.rst": {
            "size_delta": 0,
            "size": 0
          },
          "Documentation/kernel-parameters.txt": {
            "size_delta": 0,
            "size": 0
          },
          "Documentation/x86/tsx_async_abort.rst": {
            "size_delta": 0,
            "size": 0
          },
          "Makefile": {
            "size_delta": 0,
            "size": 0
          },
          "arch/mips/bcm63xx/reset.c": {
            "size_delta": 0,
            "size": 0
          },
          "arch/powerpc/Makefile": {
            "size_delta": 0,
            "size": 0
          },
          "arch/powerpc/boot/wrapper": {
            "size_delta": 0,
            "size": 0
          },
          "arch/x86/Kconfig": {
            "size_delta": 0,
            "size": 0
          },
          "arch/x86/include/asm/cpufeatures.h": {
            "size_delta": 0,
            "size": 0
          },
          "arch/x86/include/asm/kvm_host.h": {
            "size_delta": 0,
            "size": 0
          },
          "arch/x86/include/asm/msr-index.h": {
            "size_delta": 0,
            "size": 0
          },
          "arch/x86/include/asm/nospec-branch.h": {
            "size_delta": 0,
            "size": 0
          },
          "arch/x86/include/asm/processor.h": {
            "size_delta": 0,
            "size": 0
          },
          "arch/x86/kernel/cpu/Makefile": {
            "size_delta": 0,
            "size": 0
          },
          "arch/x86/kernel/cpu/bugs.c": {
            "size_delta": 0,
            "size": 0
          },
          "arch/x86/kernel/cpu/common.c": {
            "size_delta": 0,
            "size": 0
          },
          "arch/x86/kernel/cpu/cpu.h": {
            "size_delta": 0,
            "size": 0
          },
          "arch/x86/kernel/cpu/intel.c": {
            "size_delta": 0,
            "size": 0
          },
          "arch/x86/kernel/cpu/tsx.c": {
            "size_delta": 0,
            "size": 0
          },
          "arch/x86/kvm/cpuid.c": {
            "size_delta": 0,
            "size": 0
          },
          "arch/x86/kvm/vmx.c": {
            "size_delta": 0,
            "size": 0
          },
          "arch/x86/kvm/x86.c": {
            "size_delta": 0,
            "size": 0
          },
          "drivers/base/cpu.c": {
            "size_delta": 0,
            "size": 0
          },
          "include/linux/cpu.h": {
            "size_delta": 0,
            "size": 0
          }
        }
      }
    },
    {
      "host": "chromium-review.googlesource.com",
      "change_number": 1922269,
      "patch_set": 1,
      "info": {
        "_number": 1922269,
        "id": "infra%2Fluci%2Fluci-go~main~I46fa9df260e77144e39bfd39b996a85bd01a5084",
        "change_id": "I46fa9df260e77144e39bfd39b996a85bd01a5084",
        "project": "infra/luci/luci-go",
        "branch": "main",
        "topic": "",
        "hashtags": [],
        "subject": "gerrit: add ListFiles endpoint to Gerrit API client",
        "status": "MERGED",
        "created": "2019-11-18 19:00:57.000000000",
        "updated": "2019-11-19 03:00:54.000000000",
        "mergeable": false,
        "messages": null,
        "submitted": "2019-11-18 20:08:00.000000000",
        "submit_type": "",
        "insertions": 1243,
        "deletions": 870,
        "unresolved_comment_count": 0,
        "has_review_started": true,
        "owner": {
          "_account_id": 1318707
        },
        "labels": null,
        "submitter": {
          "_account_id": 1111084
        },
        "reviewers": {
          "CC": null,
          "REVIEWER": null,
          "REMOVED": null
        },
        "revert_of": 0,
        "current_revision": "9eaf449bf8690527c1f77e4c2395e6eb73a0553c",
        "revisions": null,
        "_more_changes": false
      },
      "patch_set_revision": "f9e7f6f0da4c4eacf2be9f1c729d9171d19f7792",
      "revision_info": {
        "_number": 1,
        "kind": "REWORK",
        "ref": "refs/changes/69/1922269/1",
        "uploader": {
          "_account_id": 1318707
        },
        "commit": {
          "author": {},
          "committer": {}
        },
        "files": {
          "common/api/gerrit/rest.go": {
            "lines_inserted": 21,
            "size_delta": 774,
            "size": 16263
          },
          "common/api/gerrit/rest_test.go": {
            "lines_inserted": 44,
            "size_delta": 1148,
            "size": 8928
          },
          "common/proto/gerrit/gerrit.mock.pb.go": {
            "lines_inserted": 35,
            "size_delta": 1391,
            "size": 16198
          },
          "common/proto/gerrit/gerrit.pb.go": {
            "lines_inserted": 297,
            "lines_deleted": 115,
            "size_delta": 7033,
            "size": 88887
          },
          "common/proto/gerrit/gerrit.proto": {
            "lines_inserted": 32,
            "size_delta": 1068,
            "size": 17798
          },
          "common/proto/gerrit/pb.discovery.go": {
            "lines_inserted": 795,
            "lines_deleted": 755,
            "size_delta": 2536,
            "size": 53924
          }
        }
      }
    }
  ]
}
