from django.shortcuts import get_object_or_404
from django.db import models
from django.contrib.auth import get_user_model
from .models import Workstation, WorkstationMember, WorkstationInvite, WorkstationVersion
from .serializers import WorkstationSerializer, WorkstationInviteSerializer, UserSearchSerializer, WorkstationVersionSerializer

User = get_user_model()

class WorkstationService:
    @staticmethod
    def get_user_workstations(user):
        """Get all workstations where the user is a member."""
        return Workstation.objects.filter(members__user=user).distinct().order_by('-created_at')

    @staticmethod
    def create_workstation(user, data):
        """Create a new workstation and make the user the owner/member."""
        serializer = WorkstationSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        workstation = serializer.save(owner=user)
        
        # Automatically make owner a member with OWNER role
        WorkstationMember.objects.create(
            workstation=workstation,
            user=user,
            role='OWNER'
        )
        return workstation

    @staticmethod
    def get_workstation_detail(user, workstation_id):
        """Get workstation details if the user is a member."""
        return get_object_or_404(Workstation, id=workstation_id, members__user=user)

    @staticmethod
    def update_workstation(user, workstation_id, data):
        """Update workstation if the user has OWNER or EDITOR role."""
        workstation = get_object_or_404(
            Workstation, 
            id=workstation_id, 
            members__user=user, 
            members__role__in=['OWNER', 'EDITOR']
        )
        serializer = WorkstationSerializer(workstation, data=data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        if 'content' in data:
            WorkstationVersion.objects.create(
                workstation=workstation,
                content=data['content'],
                saved_by=user
            )

        return workstation

    @staticmethod
    def get_versions(user, workstation_id):
        """Get all versions for a workstation."""
        workstation = get_object_or_404(
            Workstation, 
            id=workstation_id, 
            members__user=user
        )
        return workstation.versions.all()

    @staticmethod
    def restore_version(user, workstation_id, version_id):
        """Restore a workstation to a specific version."""
        workstation = get_object_or_404(
            Workstation, 
            id=workstation_id, 
            members__user=user,
            members__role__in=['OWNER', 'EDITOR']
        )
        version = get_object_or_404(WorkstationVersion, id=version_id, workstation=workstation)
        
        workstation.content = version.content
        workstation.save()

        WorkstationVersion.objects.create(
            workstation=workstation,
            content=workstation.content,
            saved_by=user
        )
        return workstation

    @staticmethod
    def delete_version(user, workstation_id, version_id):
        """Delete a version. Only the workstation owner or the version author may delete.
        If the deleted version is the latest, the workstation is rolled back to the previous one."""
        workstation = get_object_or_404(
            Workstation,
            id=workstation_id,
            members__user=user
        )
        version = get_object_or_404(WorkstationVersion, id=version_id, workstation=workstation)

        is_workstation_owner = workstation.owner == user
        is_version_author = version.saved_by == user

        if not (is_workstation_owner or is_version_author):
            raise PermissionError("You do not have permission to delete this version.")

        # Check if this is the most recent version before deleting
        latest = workstation.versions.order_by('-created_at').first()
        is_latest = latest and latest.id == version.id

        version.delete()

        rolled_back = False
        if is_latest:
            # Promote the new latest version to the workstation's live content
            new_latest = workstation.versions.order_by('-created_at').first()
            workstation.content = new_latest.content if new_latest else ""
            workstation.save()
            rolled_back = True

        return workstation, rolled_back

    @staticmethod
    def delete_workstation(user, workstation_id):
        """Delete workstation if the user is the owner."""
        workstation = get_object_or_404(Workstation, id=workstation_id, owner=user)
        workstation.delete()
        return True

    @staticmethod
    def update_member_role(requesting_user, workstation_id, member_id, new_role):
        """Update a member's role. Only the workstation owner can do this."""
        workstation = get_object_or_404(Workstation, id=workstation_id, owner=requesting_user)
        if new_role not in ['EDITOR', 'VIEWER']:
            raise ValueError("Invalid role. Must be EDITOR or VIEWER.")
        member = get_object_or_404(WorkstationMember, id=member_id, workstation=workstation)
        if member.role == 'OWNER':
            raise PermissionError("Cannot change the owner's role.")
        member.role = new_role
        member.save()
        return member

    @staticmethod
    def remove_member(requesting_user, workstation_id, member_id):
        """Remove a collaborator. Only the workstation owner can do this."""
        workstation = get_object_or_404(Workstation, id=workstation_id, owner=requesting_user)
        member = get_object_or_404(WorkstationMember, id=member_id, workstation=workstation)
        if member.role == 'OWNER':
            raise PermissionError("Cannot remove the workstation owner.")
        member.delete()
        return True

    @staticmethod
    def search_users(user, query):
        """Search for users to invite, excluding the current user."""
        if len(query) < 2:
            return []
        
        return User.objects.filter(
            models.Q(email__icontains=query) | 
            models.Q(first_name__icontains=query) | 
            models.Q(last_name__icontains=query)
        ).exclude(id=user.id)[:10]

    @staticmethod
    def get_pending_invites(user):
        """Get all pending invites for the user."""
        return WorkstationInvite.objects.filter(invitee=user, status='PENDING').order_by('-created_at')

    @staticmethod
    def send_invite(inviter, workstation_id, invitee_id, role='EDITOR'):
        """Send an invite to a user."""
        workstation = get_object_or_404(
            Workstation, 
            id=workstation_id, 
            members__user=inviter, 
            members__role__in=['OWNER', 'EDITOR']
        )
        invitee = get_object_or_404(User, id=invitee_id)

        # Check if already a member
        if WorkstationMember.objects.filter(workstation=workstation, user=invitee).exists():
            raise Exception("User is already a member")

        # Check if already has a pending invite
        if WorkstationInvite.objects.filter(workstation=workstation, invitee=invitee, status='PENDING').exists():
            raise Exception("Invite already sent")

        invite = WorkstationInvite.objects.create(
            workstation=workstation,
            inviter=inviter,
            invitee=invitee,
            role=role
        )
        return invite

    @staticmethod
    def respond_to_invite(user, invite_id, action):
        """Respond to a workstation invite."""
        invite = get_object_or_404(WorkstationInvite, id=invite_id, invitee=user, status='PENDING')

        if action == 'ACCEPT':
            invite.status = 'ACCEPTED'
            invite.save()
            # Create membership
            WorkstationMember.objects.get_or_create(
                workstation=invite.workstation,
                user=invite.invitee,
                defaults={'role': invite.role}
            )
            return {"message": "Invite accepted"}
        elif action == 'REJECT':
            invite.status = 'REJECTED'
            invite.save()
            return {"message": "Invite rejected"}
        
        raise ValueError("Invalid action")
