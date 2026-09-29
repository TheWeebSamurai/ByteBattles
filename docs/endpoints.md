# API Endpoints For Backend

## Authentication

D - `POST /auth/register` : new userss can register
D - `POST /auth/login` : existing userss can login
D - `POST /auth/refresh`: get access token from refresh token
 - `POST /auth/bootstrap-admin` : promote the first admin using the configured `X-Bootstrap-Secret` header (one-time)
S - `POST /auth/logout` : loggedin users can logout (NOT NEEDED RIGHT NOW)                                       (Loggedin: users)

## Users (Profile)

 - `GET /users/<usersname>` : get profile of any users
 - `GET /users/<usersname>/submissions` : get all submissions of any users
 - `GET /users/<usersname>/solved_problems` : get all solved problems of any users

D - `GET /users/me` : get profile of logged in users                                                             (Loggedin: users)
D - `PATCH /users/me` : update logged in users's details                                                         (Loggedin: users)
D - `DELETE /users/me` : delete logged in users                                                                  (Loggedin: users)
 - `POST /users/<username>/promote` : promote a registered user to ADMIN (Loggedin: Admin)

## Problems

D - `GET /problems` : search/filter problems with `difficulty`, `tag`, and `title`; paginated with `items`, `total`, `page`, `limit`, and `has_more` (Loggedin: Admin | None)
D - `GET /problems/<id>` : get details for the problem with given id                                             (Loggedin: Admin | None)

D - `POST /problems/tag` : create a new tag                                                                      (Loggedin: Admin)

D - `POST /problems` : create a new problem                                                                      (Loggedin: Admin)
 - `PATCH /problems/<id>` : partially edit problem metadata, tags, and visibility (JSON; omitted fields stay unchanged) (Loggedin: Admin)
 - `PUT /problems/<id>/testcases` : replace the complete testcase set with a validated ZIP (Loggedin: Admin)
 - `DELETE /problems/<id>` : delete problem with given id                                                       (Loggedin: Admin)
 - `POST /problems/<id>/rejudge` : re run all the submissions of the problem with given id                      (Loggedin: Admin)

## Submissions

D - `POST /submissions` : create new submission (5 per user per 60 seconds; excess requests return 429)        (Loggedin: users)
D - `GET /submissions` : view all submissions for users {prob_id, username(optional) : query param}
D - `GET /submissions/<sub_id>` : get details of submission with sub_id

# NOTES:

 - Verify that user is verified in every user query
 - Verify that problem is visible in every problem query
 - Process the file read for testcase data zip file in chunks