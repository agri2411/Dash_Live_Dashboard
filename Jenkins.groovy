#!/usr/bin/env groovy
def APP_NAME = null
def IMAGE_TAG = null
def DOCKER_IMAGE = null
def DOCKER_IMAGE_NAME = null
def DOCKER_IMAGE_PUSH = null
def STACK = null
def TRACK = null
def VERSION = null
def CONFIG_FILENAME = null
def commitid = null
def DEPLOY = true

def msg = ''
def app_name = ''
def app_workspace = "./" // default workdir
def app_requirements_path = ""
def short_sha = ""
def deploymentTrack = ""
def envConfig = ""
def deploymentJson = {}

def notifySlack(String buildStatus = "STARTED", String customMsg = "", String app_name = "") {
    // Build status of null means success.
    buildStatus = buildStatus ?: 'SUCCESS'
    def color

    if (buildStatus == 'STARTED') {
        color = '#D4DADF'
    } else if (buildStatus == 'SUCCESS') {
        color = '#BDFFC3'
    } else if (buildStatus == 'UNSTABLE') {
        color = '#FFFE89'
    } else {
        color = '#FF9FA1'
    }

    def msg = "Repository: ${env.GIT_URL}\nBranch : ${env.GIT_BRANCH}\nApp Name: ${app_name} \nAuthor : ${env.CHANGE_AUTHOR_DISPLAY_NAME}\nAuthor Email : ${env.CHANGE_AUTHOR_EMAIL}\n Message: ```${customMsg}```\n${buildStatus}: `${env.JOB_NAME}` #${env.BUILD_NUMBER}:\n${env.BUILD_URL}"

    slackSend channel: 'checkmarx-pipeline', color: color, message: msg
}

def check_app_workspace_path(app_path_list) {
   def app_dir = "."
   app_path_list = app_path_list.dropRight(1)
   if (app_path_list.size() < 1) {
      return app_dir // return app default workspace path
   }
   json_path = "./${app_path_list.join('/')}/requirements.txt"
   def exists = fileExists("${json_path}")
   if (exists) {
       return app_path_list.join('/') + '/' // return app workspace path
   }
   return check_app_workspace_path(app_path_list)
}

def change_app_dir(sourceChanged) {
    def app_dir = '.'
    if (sourceChanged.size()) {
        def is_app_path = false
        def app_path = ''
        int max_count = 0
        for (int i = 0; i < sourceChanged.size(); i++) {
            if (sourceChanged[i].contains('/')) {
                int count = sourceChanged[i].length() - sourceChanged[i].replaceAll("/", "").length() // check max depth path of file
                if (max_count < count) {
                    max_count = count
                    is_app_path = true
                    app_path = sourceChanged[i]
                }
            }
        }
        if (is_app_path) {
            app_path_list = app_path.split('/')
            app_dir = check_app_workspace_path(app_path_list)
            return app_dir
        }
    }
    return app_dir
}
def build_for(){

  branch_name = "${env.GIT_BRANCH}"
  branch_name_split  = branch_name.split("-")
  buildfor = branch_name_split[0] + '-'+  branch_name_split[1]
  return buildfor
}
pipeline {
    agent {
        node {
            label 'docker_node2'
        }
    }
    parameters {
        booleanParam(name: 'SKIP_TEST', defaultValue: false, description: 'Skip Test')
    }

    stages {
        stage('PREP') {
            steps {
                cleanWs()
                checkout([
                    $class: 'GitSCM',
                    branches: scm.branches,
                    doGenerateSubmoduleConfigurations: false,
                    extensions: scm.extensions + [
                        [$class: 'CleanBeforeCheckout'],
                        [$class: 'SubmoduleOption', disableSubmodules: false, recursiveSubmodules: true, reference: '', trackingSubmodules: false]
                    ],
                    submoduleCfg: [],
                    userRemoteConfigs: scm.userRemoteConfigs])

                script {
                    if (env.BRANCH_NAME && env.BRANCH_NAME.startsWith("PR-")) {
                        List<String> sourceChanged = sh(returnStdout: true, script: "git  --no-pager diff --name-only origin/${env.CHANGE_TARGET}").split()
                        echo "${sourceChanged}"
                        app_workspace = change_app_dir(sourceChanged)
                        echo "Changed to workspace ${app_workspace}"
                        sh """
                        cd ${app_workspace}
                        """
                    } else {
                        List<String> sourceMerged = sh(returnStdout: true, script: 'git rev-list --min-parents=1 --max-count=1 HEAD | git log -m -1 --name-only --pretty="format:"').split()
                        commitid = sh(returnStdout: true, script: 'git rev-parse HEAD').trim()
                        short_sha = sh(returnStdout: true, script: 'git rev-parse --short HEAD').trim()
                        app_workspace = change_app_dir(sourceMerged)
                        echo "Changed to workspace ${app_workspace}"
                        sh """
                        cd ${app_workspace}
                        """
                    }
                    
                    if (app_workspace == '.') {
			echo "current workspace is ${app_workspace}"
			deploymentJson = readJSON file: "./Deployment-target.json"
			//deploymentTrack = deploymentJson['envs'][0]
                        app_requirements_path = "requirements.txt"
			echo "Using config file: ${app_requirements_path}"
                        //app_requirements_path = "${app_workspace}/${CONFIG_FILENAME}/requirements.txt"
                    } else {
                        //app_requirements_path = "./${app_workspace}requirements.txt"
                        echo "current workspace is in else ${app_workspace}"
			deploymentJson = readJSON file: "./Deployment-target.json"
			//deploymentTrack = deploymentJson['envs'][0]
			//CONFIG_FILENAME = deploymentJson['envs'][0]['config_filename']
                        app_requirements_path = "requirements.txt"
			echo "Using config file in else: ${app_requirements_path}"
                    }

                    // Extracting values from Deployment-target.json
                    try {
                        deploymentJson = readJSON file: "./Deployment-target.json"
			//CONFIG_FILENAME = deploymentJson['envs'][0]['config_filename']
			//echo "Using config file: ${CONFIG_FILENAME}"
                        //app_requirements_path = "${app_workspace}/${CONFIG_FILENAME}"
                    } catch(FileNotFoundException ex) {
                        echo "${ex}"
                        DEPLOY = false
                    }

                    if(DEPLOY && deploymentJson.containsKey('envs')){
                      for(int i=0; i < deploymentJson['envs'].size(); i++){
                      deploymentTrack = deploymentJson['envs'][0]
                      // echo "${deploymentTrack}"
                      STACK = deploymentTrack['stack']
		      VERSION = deploymentTrack['version']
                      if(STACK == 'c'){
                        APP_NAME = deploymentTrack['app_name']
                        //VERSION = "1.1.0"
                        IMAGE_TAG = "${VERSION}.${env.BUILD_NUMBER}-${short_sha}"
                        DOCKER_IMAGE_NAME = "copart/${APP_NAME}:${IMAGE_TAG}"
                        deploymentTrack['app_name'] = APP_NAME

                      }
                    }
                   } else {
                        DEPLOY = false
                    }
                }
            }

            post {
                failure {
                    echo 'Failed cloning the repo'
                }
            }
        }

        stage("SonarQube analysis") {
            when {
                expression { env.BRANCH_NAME && env.BRANCH_NAME.startsWith("PR-")}
            }
            environment {
                scannerHome = tool 'SonarQube Scanner'
            }
            steps {
                withSonarQubeEnv(credentialsId: '33f52f12-e934-4aaa-9cea-68b4243d445e', installationName: 'Sonar') {
                    sh """
                    cd ${app_workspace}
                    ${scannerHome}/bin/sonar-scanner -Dsonar.projectKey=${APP_NAME} -Dsonar.projectName=${APP_NAME} -Dsonar.projectVersion=${VERSION} -Dsonar.sources=./src
                    """
                }
            }
        }
        
         stage("Quality Gate") {
                when {
                expression { env.BRANCH_NAME && env.BRANCH_NAME.startsWith("PR-")}
                }
                steps {
                  timeout(time: 5, unit: 'MINUTES') {
                    waitForQualityGate(webhookSecretId: 'Sonar-Secret' , abortPipeline: true)
                  }
              }
              }

        stage('Build && Push Image') {
            when {
                expression { env.BRANCH_NAME && env.BRANCH_NAME ==~/.*master.*|release-\d\.\d+.*/ && DEPLOY}
            }
            steps {
                script {
		    //def workspace = "${CONFIG_FILENAME}/"
		    //CONFIG_FILENAME = deploymentTrack['config_filename']
                   DOCKER_IMAGE_PUSH = docker.build("${DOCKER_IMAGE_NAME}", "--build-arg STACK=${STACK} --build-arg CONFIG_FILENAME=${CONFIG_FILENAME} .")
                    //DOCKER_IMAGE_PUSH = docker.build("${DOCKER_IMAGE_NAME}", "--build-arg STACK=${STACK} --build-arg -f ${CONFIG_FILENAME}/Dockerfile ${app_workspace} ")
                    docker.withRegistry('https://dockerregistry.copart.com/', '1020f3f0-1828-4ca6-8319-c6cdbba9fe80') {
                        DOCKER_IMAGE_PUSH.push("${IMAGE_TAG}")
                    }
                    echo "Pushed Docker image: ${DOCKER_IMAGE_NAME}"
                }
		    logbook enabled: true, gitCommitSha: commitid
            }
        } 
        
        stage('Deploy') {
            when {
                expression { env.BRANCH_NAME && (env.BRANCH_NAME ==~/.*master.*|.*release.*|release-\d\.\d+.*/) && DEPLOY }
            }
            steps {
                ws("${env.workspace}/${app_workspace}") {
                    script {
                        for (int i = 0; i < deploymentJson['envs'].size(); i++)
			    {
                            TRACK = deploymentTrack['track']
                            STACK =  deploymentTrack['stack']
                            APP_NAME = deploymentTrack['app_name']
                            def payload = """{
                            "secret": "SuperSecret",
                            "stack": "${STACK}",
                            "track": "${TRACK}",
                            "artifacts": [
                            {
                                "type": "docker/image",
                                "name": "dockerregistry.copart.com/copart/${APP_NAME}",
                                "version": "${IMAGE_TAG}",
                                "artifactAccount": "docker-registry",
                                "reference": "dockerregistry.copart.com/copart/${APP_NAME}:${IMAGE_TAG}"
                          }
                        ]
                      } """
                        echo "${payload}"
                        // sh "curl -v -X POST -H 'Content-type: application/json' -d '${payload}' https://rnq-spinnaker.k8s.copart.com/gate/webhooks/webhook/demo-deploy --insecure"
                        def url = "https://rnq-spinnaker.k8s.copart.com/gate/webhooks/webhook/${APP_NAME}"
                        echo "${url}"
			response = httpRequest contentType: 'APPLICATION_JSON', httpMode: 'POST', requestBody: payload, url: url, ignoreSslErrors: true, customHeaders: [[name: 'X-Spinnaker-Secret', value: 'NXsytwluSdJfzmsr8TbkM']], validResponseCodes: '200', quiet: true
                        echo "status: ${response.status}"
                        }
                    }
                }
            }
        }
                       }
					} 
    post {
        always {
            cleanWs()
            deleteDir()
        }
    }
