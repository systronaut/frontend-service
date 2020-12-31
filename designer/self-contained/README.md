This docker compose file runs draw.io diagram editor without depending on any draw.io online services (e.g., export service, plantUml, ...) and with support of Google Drive, Microsoft OneDrive, ...

### Adding fonts to improve generated PDFs and images

The docker-compose file bind the `fonts` volume into the running container system fonts.

The best option for Windows users is to copy the contents of `Windowsdrive:/Windows/Fonts` into `fonts` folder. These fonts are copyrighted and cannot be re-distributed freely.

# Configuration

You can customize the application by setting the following environment variables.

* `DRAWIO_BASE_URL`: Your deployment base URL. For example, `https://drawio.example.com` or `https://www.example.com/drawio` if it is deployed into a folder.
* `DRAWIO_CSP_HEADER`: (Optional) Your website Content-Security-Policy if you want to customize it.
* `DRAWIO_VIEWER_URL`: (Optional) If you want to host a draw.io viewer also, set the viewer URL
* `DRAWIO_CONFIG`: (Optional) draw.io configuration JSON. [Documentation](https://desk.draw.io/support/solutions/articles/16000058316)

## Google Drive

You will need to create a project at [Google API Console](https://console.developers.google.com/apis) and create [Credentials](https://console.developers.google.com/apis/credentials) of type "Create OAuth client ID" -> Web Application. This option will be disabled until you create "OAuth consent screen" from the link in warning message bar. In the "OAuth consent screen" configuration, enter the "Application name" and "Authorized domains". In the "Create OAuth client ID" configuration, enter the required information and note that "Authorized redirect URIs" is `[your-draw.io-hostname]/google`. For example, if you host draw.io at `https://drawio.example.com`, then "Authorized redirect URIs" whould be `https://drawio.example.com/google` and "Authorized JavaScript origins" would be `https://drawio.example.com`.

Set the values of the generated "Client ID" and "Client secret" into environment variables `DRAWIO_GOOGLE_CLIENT_ID` and `DRAWIO_GOOGLE_CLIENT_SECRET`. Also, set `DRAWIO_GOOGLE_APP_ID` environment variable to your Google App ID. APP ID is the number before the dash in the CLIENT ID. For example, if CLIENT ID is `123456789-abc...`, then APP ID is `123456789`

If you want to host a draw.io viewer also, you can create another client ID for the viewer. Viewer has read-only access to Drive files.

Set the values of the generated "Client ID" and "Client secret" into environment variables `DRAWIO_GOOGLE_VIEWER_CLIENT_ID` and `DRAWIO_GOOGLE_VIEWER_CLIENT_SECRET`. Also, set `DRAWIO_GOOGLE_VIEWER_APP_ID` environment variable to your Google App ID.

## Microsoft OneDrive

You will need to create and application in order to use MS Graph APIs. Follow the information on [how to register your app](https://docs.microsoft.com/en-us/graph/auth-register-app-v2) and [how to use the APIs](https://docs.microsoft.com/en-us/graph/use-the-api).

Once you registered your application, from Microsoft Azure UI, select your new app, then "Authentication". From Authentication, enter your redirect URIs. draw.io requires two redirect URIs `[your-draw.io-hostname]/microsoft` and `[your-draw.io-hostname]/onedrive3.html`. For example, if you host draw.io at `https://drawio.example.com`, then redirect URIs would be `https://drawio.example.com/microsoft` and `https://drawio.example.com/onedrive3.html`

In "Advanced settings" on the same page, enable "Access tokens" and "ID tokens" check boxes. To get the "Client secret", select "Certificates & secrets" page from the menu, then click "+ New client secret" button. Finally, from the "Overview" page in the menu, you can find the "Application (client) ID". 

Set the client ID and secret into environment variables `DRAWIO_MSGRAPH_CLIENT_ID` and `DRAWIO_MSGRAPH_CLIENT_SECRET`.

## Gitlab

Set the following environment variables to enable Gitlab integration.

* `DRAWIO_GITLAB_ID`: Your Gitlab ID
* `DRAWIO_GITLAB_URL`: Your Gitlab URL

## EMF Converter

This service is currently used by VSDX importer for converting EMF files in VSDX files. If you don't plan to use VSDX importer or your VSDX files don't contain EMF files, then this service is not important to you.

This service is based on [Cloud Convert](http://cloudconvert.com). You will need to register for an account and set the environment variable `DRAWIO_CLOUD_CONVERT_APIKEY` to the API KEY. We use API **V1** API KEY.

## Real-time Collaboration

draw.io supports real-time collaboration with Google Drive and Microsoft OneDrive. In order to enable this feature, you need to a real-time notification service (we support [pusher.com](https://pusher.com/) and [AWS IoT](https://aws.amazon.com/iot-core/?nc=sn&loc=2&dn=3)). This docker compose file is set to use AWS IoT.
You need to follow the instructions in `etc/mxPusher` folder to setup a lambda function for temporary keys as well as setting a role for that lambda function. 

Then, you need to create a `Thing` in AWS IoT core console (e.g, `mxPusher`). Next, from "Secure", select "Certificates", then "Create". Download the certificate ".cert.pem" file, the private and public key files, and root CA (we tested with "Amazon Root CA 1"). Finally, click "Activate" and click "Attach a policy". In the "Add authorization to certificate" page that will open, click "Create new policy" button, give it a name and click "Advanced mode". Copy and paste the following JSON.

```JSON
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "iot:Connect",
        "iot:Subscribe",
        "iot:Publish",
        "iot:Receive"
      ],
      "Resource": "*"
    }
  ]
}
```
Finally, you will need to attach the "Thing" to this certificate. Select "Actions", menu in "Certificates" -> "Attach thing" and select the thing you just created.

Now set the following environment variables:

* `DRAWIO_CACHE_DOMAIN`: Your deployment domain (e.g, `drawio.example.com`)
* `DRAWIO_IOT_ENDPOINT`: From the AWS IoT Core, select the "Thing" you created, then "Interact". Set this variable to the listed HTTPS endpoint.
* `DRAWIO_IOT_CERT_PEM`: The content of the certificate file downloaded above.
* `DRAWIO_IOT_PRIVATE_KEY`: The content of the private key file downloaded above.
* `DRAWIO_IOT_ROOT_CA`: The content of the root certificate file downloaded above.
* `DRAWIO_MXPUSHER_ENDPOINT`: The temporary keys Lambda function URL (from `etc/mxPusher` folder)

If you want to deploy to multiple servers/nodes. Then, a central cache is needed. We support memcached.

* `DRAWIO_MEMCACHED_ENDPOINT`: Your memcached server instance url and port (e.g, `10.0.0.111:11211`)

# AWS Deployment

You can deploy this docker compose easily to AWS ECS. Follow the instructions in this [tutorial](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/ecs-cli-tutorial-ec2.html) to install Amazonn ECS CLI, create a cluster, and deploy "self-contained" docker compose file to it. We recommend EC2 deployment as it is easy to connect with Amazon ElastiCache if you plan to use real-time collaboration.
You will need to chnage port mapping to 80 and 443 to support standard HTTP and HTTPS ports in `docker-compose.yml`. Don't forget to allow access to these ports in the security group inbound rules. Also, it is required to set `DRAWIO_BASE_URL` environment variable in order to have a fully functional deployment. Set the other environment variables as described above to enable other services and features as needed.

Refer to the main [README](https://github.com/jgraph/docker-drawio) file for how to configure **Let's Encrypt**.

If you are not planning to use Amazon ElastiCache memcached, remove the `DRAWIO_MEMCACHED_ENDPOINT` line from the docker compose file.

## Amazon ElastiCache

It is strongly recommended to use Amazon ElastiCache memcached (or similar memcached service) to support multiple nodes in the cluster.
Navigate to AWS ElastiCache dashboard, create a cluster (Memcached) with all standard settings except for "Node type" which can be as small as "cache.t2.micro". Then, in "Advanced Memcached settings", select "Create new" in the "Subnet group" field and select VPC used in your ECS. Also, you can select all subnets in that VPC. Then, ensure that the selected security group allow inbound access to memcached port (e.g, 11211). You can select the same security group as ECS and allow inbound access to memcached port 11211 only from this cache cluster.
Finally, set the environment variable `DRAWIO_MEMCACHED_ENDPOINT` to the cluster "Configuration Endpoint"

**Note**: Currently, the real-time features are available in `jgraph/drawio-expr` image only and not yet available in `jgraph/drawio`.