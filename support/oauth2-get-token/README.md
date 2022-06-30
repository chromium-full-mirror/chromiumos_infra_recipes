# OAUTH2 get token

## Local testing

To test locally you'll need to authenticate with gerrit and cloud OAuth scopes:

```shell
luci-auth login -scopes 'https://www.googleapis.com/auth/userinfo.email https://www.googleapis.com/auth/gerritcodereview https://www.googleapis.com/auth/cloud-platform'
```

then simply call the program:

```shell
go run oauth2-get-token/oauth2_get_token.go
```
