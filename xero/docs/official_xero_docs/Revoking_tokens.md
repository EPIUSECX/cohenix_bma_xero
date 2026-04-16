# Revoking tokens

You can revoke a user's refresh token and remove all their connections to your app by making a request to the revocation endpoint.

To revoke a refresh token you need to POST to the revocation endpoint:

`https://identity.xero.com/connect/revocation`

The request will require an authorization header containing your app's client_id and client_secret:

```
Authorization: "Basic " + base64encode(client_id + ":" + client_secret)
```

The request body will contain the refresh token being revoked:

```
token=Your refresh token
```

## Example Request

```http
POST https://identity.xero.com/connect/revocation
authorization: "Basic " + base64encode(client_id + ":" + client_secret)
Content-Type: application/x-www-form-urlencoded

token=xxxxxx
```

A successful revocation request will return a 200 response with an empty body.