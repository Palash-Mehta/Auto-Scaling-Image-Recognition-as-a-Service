# CSE-546-Project-1

<------ Web Tier set up ------>

SSH into your EC2 instance run the following commands 
1) sudo apt-get update
2) sudo apt-get install python3-pip
3) pip3 install virtualenv
4) mkdir flaskproject && cd flaskproject

This directory will host all the files for our Flask web application. Once in this directory, run the following commands
1) python3 -m virtualenv venv
2) . venv/bin/activate
3) pip install FLask

The flask application will run on top of Apache web server. So install Apache in the instance.
1) sudo apt-get install apache2 libapache2-mod-wsgi-py3
2) sudo ln -sT ~/flaskproject /var/www/html/flaskproject
3) sudo a2enmod wsgi

We will then configure the Apache Web Server
1) sudo vi /etc/apache2/sites-enabled/000-default.conf
2) Paste this in right after the line with DocumentRoot /var/www/html </br>

```xml
WSGIDaemonProcess flaskproject threads=5 </br>
WSGIScriptAlias / /var/www/html/flaskproject/app.wsgi </br>

<Directory flaskproject> </br>
	WSGIProcessGroup flaskproject </br>
	WSGIApplicationGroup %{GLOBAL} </br>
	Order deny,allow </br>
	Allow from all </br>
</Directory> </br>
```
Finally, copy all the files inside the WebTier folder into the flaskproject directory (Using SCP or directly copy pasting)
Restart the web server by running the following command : sudo apachectl restart
