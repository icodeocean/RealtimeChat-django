from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, authenticate, logout
from django.http import HttpResponse
from django.conf import settings
from django.core.files.storage import default_storage
from django.core.files.storage import FileSystemStorage
import os
import cv2
import json
import base64
import requests
import tempfile
from django.core import files

from friend.utils import get_friend_request_or_false
from friend.friend_request_status import FriendRequestStatus
from friend.models import FriendList, FriendRequest
from account.models import Account, get_profile_image_filepath
from account.forms import RegistrationForm, AccountAuthenticationForm, AccountUpdateForm
TEMP_PROFILE_IMAGE_NAME = "temp_profile_image.png"


# This is basically almost exactly the same as friends/friend_list_view
def account_search_view(request, *args, **kwargs):
	context = {}
	if request.method == "GET":
		search_query = request.GET.get("q")
		if len(search_query) > 0:
			search_results = Account.objects.filter(email__icontains=search_query).filter(username__icontains=search_query).distinct()
			user = request.user
			if user.is_authenticated:
				accounts = [] # [(account1, True), (account2, False), ...]
				# get the authenticated users friend list
				auth_user_friend_list = FriendList.objects.get(user=user)
				for account in search_results:
					accounts.append((account, auth_user_friend_list.is_mutual_friend(account)))
				context['accounts'] = accounts
			else:
				context['accounts'] = search_results
	return render(request, "account/search_results.html", context)



def save_temp_profile_image_from_base64String(imageString, user):
	INCORRECT_PADDING_EXCEPTION = "Incorrect padding"
	try:
		if not os.path.exists(settings.TEMP):
			os.mkdir(settings.TEMP)
		if not os.path.exists(settings.TEMP + "/" + str(user.pk)):
			os.mkdir(settings.TEMP + "/" + str(user.pk))
		url = os.path.join(settings.TEMP + "/" + str(user.pk),TEMP_PROFILE_IMAGE_NAME)
		storage = FileSystemStorage(location=url)
		image = base64.b64decode(imageString)
		with storage.open('', 'wb+') as destination:
			destination.write(image)
			destination.close()
		return url
	except Exception as e:
		print("exception: " + str(e))
		if str(e) == INCORRECT_PADDING_EXCEPTION:
			imageString += "=" * ((4 - len(imageString) % 4) % 4)
			return save_temp_profile_image_from_base64String(imageString, user)
	return None



def account_view(request, *args, **kwargs):
	"""
	- Logic here is kind of tricky
		is_self
		is_friend
			-1: NO_REQUEST_SENT
			0: THEM_SENT_TO_YOU
			1: YOU_SENT_TO_THEM
	"""
	context = {}
	username = kwargs.get("username")
	account = Account.objects.filter(username=username).first()
	if account:
		context['id'] = account.id
		context['username'] = account.username
		context['email'] = account.email
		context['profile_image'] = account.profile_image
		context['hide_email'] = account.hide_email

		friend_list = FriendList.objects.get(user=account)
		friends = friend_list.friends.all()
		context['friends'] = friends
	
		# Define template variables
		is_self = True
		is_friend = False
		request_sent = FriendRequestStatus.NO_REQUEST_SENT.value # range: ENUM -> friend/friend_request_status.FriendRequestStatus
		friend_requests = None
		user = request.user
		if user.is_authenticated and user != account:
			is_self = False
			if friends.filter(pk=user.id):
				is_friend = True
			else:
				is_friend = False
				# CASE1: Request has been sent from THEM to YOU: FriendRequestStatus.THEM_SENT_TO_YOU
				if get_friend_request_or_false(sender=account, receiver=user) != False:
					request_sent = FriendRequestStatus.THEM_SENT_TO_YOU.value
					context['pending_friend_request_id'] = get_friend_request_or_false(sender=account, receiver=user).id
				# CASE2: Request has been sent from YOU to THEM: FriendRequestStatus.YOU_SENT_TO_THEM
				elif get_friend_request_or_false(sender=user, receiver=account) != False:
					request_sent = FriendRequestStatus.YOU_SENT_TO_THEM.value
				# CASE3: No request sent from YOU or THEM: FriendRequestStatus.NO_REQUEST_SENT
				else:
					request_sent = FriendRequestStatus.NO_REQUEST_SENT.value
		else:
			try:
				friend_requests = FriendRequest.objects.filter(receiver=user, is_active=True)
			except FriendRequest.DoesNotExist:
				pass

		# Set the template variables to the values
		context['is_self'] = is_self
		context['is_friend'] = is_friend
		context['request_sent'] = request_sent
		context['friend_requests'] = friend_requests
		return render(request, "account/account.html", context)


def edit_account_view(request, *args, **kwargs):
	if not request.user.is_authenticated:
		return redirect("login")
	username = kwargs.get("username")
	account = Account.objects.filter(username=username).first()
	if account.pk != request.user.pk:
		return HttpResponse("You cannot edit someone elses profile.")
	context = {}
	if request.POST:
			form = AccountUpdateForm(request.POST, request.FILES, instance=request.user)
			if form.is_valid():
				form.save()
				new_username = form.cleaned_data['username']
				return redirect("account:view", username=new_username)
			else:
				form = AccountUpdateForm(request.POST, instance=request.user,
					initial={
						"email": account.email, 
						"username": account.username,
						"profile_image": account.profile_image,
						"hide_email": account.hide_email,
					}
				)
				context['form'] = form
	else:
		form = AccountUpdateForm(
			initial={
					"email": account.email, 
					"username": account.username,
					"profile_image": account.profile_image,
					"hide_email": account.hide_email,
				}
			)
		context['form'] = form
	context['DATA_UPLOAD_MAX_MEMORY_SIZE'] = settings.DATA_UPLOAD_MAX_MEMORY_SIZE
	return render(request, "account/edit_account.html", context)


def register_view(request, *args, **kwargs):
	user = request.user
	if user.is_authenticated: 
		return HttpResponse("You are already authenticate as " + str(user.email))

	context = {}
	if request.POST:
		form = RegistrationForm(request.POST)
		if form.is_valid():
			form.save()
			email = form.cleaned_data.get('email').lower()
			raw_password = form.cleaned_data.get('password1')
			account = authenticate(email=email, password=raw_password)
			login(request, account)
			destination = kwargs.get("next")
			if destination:
				return redirect(destination)
			return redirect('home')
		else:
			context['registration_form'] = form

	else:
		form = RegistrationForm()
		context['registration_form'] = form
	return render(request, 'account/register.html', context)


def logout_view(request):
	print("LOGGING OUT")
	logout(request)
	return redirect("home")


def login_view(request, *args, **kwargs):
	context = {}

	user = request.user
	if user.is_authenticated: 
		return redirect("home")

	destination = get_redirect_if_exists(request)
	print("destination: " + str(destination))

	if request.POST:
		form = AccountAuthenticationForm(request.POST)
		if form.is_valid():
			email = request.POST['email']
			password = request.POST['password']
			user = authenticate(email=email, password=password)

			if user:
				login(request, user)
				if destination:
					return redirect(destination)
				return redirect("home")

	else:
		form = AccountAuthenticationForm()

	context['login_form'] = form

	return render(request, "account/login.html", context)



def get_redirect_if_exists(request):
	redirect = None
	if request.GET:
		if request.GET.get("next"):
			redirect = str(request.GET.get("next"))
	return redirect



# save image to /temp/
# load image with cv2
# crop image with cv2
# save image to /temp/

def crop_image(request, *args, **kwargs):
	payload = {}
	user = request.user
	if request.POST and user.is_authenticated:
		try:
			imageString = request.POST.get("image")
			url = save_temp_profile_image_from_base64String(imageString, user)
			img = cv2.imread(url)

			cropX = int(float(str(request.POST.get("cropX"))))
			cropY = int(float(str(request.POST.get("cropY"))))
			cropWidth = int(float(str(request.POST.get("cropWidth"))))
			cropHeight = int(float(str(request.POST.get("cropHeight"))))
			if cropX < 0:
				cropX = 0
			if cropY < 0: # There is a bug with cropperjs. y can be negative.
				cropY = 0
			crop_img = img[cropY:cropY+cropHeight, cropX:cropX+cropWidth]

			cv2.imwrite(url, crop_img)
			filename = os.path.basename(url)
			mediaUrl = settings.BASE_URL + "/media/temp/" + str(user.pk) + "/" + filename

			request = requests.get(mediaUrl, stream=True)

			# Was the request OK?
			if request.status_code != requests.codes.ok:
				raise Exception("Something went wrong. Try another image.")

			# Create a temporary file
			lf = tempfile.NamedTemporaryFile()
			# Read the streamed image in sections
			for block in request.iter_content(1024 * 8):
				# If no more file then stop
				if not block:
					break

				# Write image block to temporary file
				lf.write(block)

			# Save the temporary image to the model#
			# This saves the model so be sure that is it valid
			user.profile_image.save("profile_image.png", files.File(lf))

			payload['result'] = "success"
			payload['cropped_profile_image'] = mediaUrl
			
		except Exception as e:
			print("exception: " + str(e))
			payload['result'] = "error"
			payload['exception'] = str(e)
	return HttpResponse(json.dumps(payload), content_type="application/json")

