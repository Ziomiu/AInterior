import { useEffect, useState } from "react";
import axios from "axios";
import { useNavigate } from "react-router-dom";

import Button from "../../components/ui/Button";
import Input from "../../components/ui/Input";

export default function UsersList() {
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(false);
  const [editingUser, setEditingUser] = useState(null);
  const [formData, setFormData] = useState({
    first_name: "",
    last_name: "",
    email: "",
    role: "",
  });
  const navigate = useNavigate();

  useEffect(() => {
    const fetchUsers = async () => {
      setLoading(true);
      try {
        const res = await axios.get(`/api/admin/users`, {
          headers: {
            Authorization: `Bearer ${localStorage.getItem("token")}`,
          },
        });

        const usersWithId = (res.data.users || []).map((u) => ({
          ...u,
          id: u.id || u._id,
        }));

        setUsers(usersWithId);
      } catch (error) {
        console.error("Error fetching users:", error.response?.data || error.message);
      } finally {
        setLoading(false);
      }
    };

    fetchUsers();
  }, []);

  const openEditModal = (user) => {
    setEditingUser(user);
    setFormData({
      first_name: user.first_name,
      last_name: user.last_name,
      email: user.email,
      role: user.role,
    });
  };

  const handleChange = (e) => {
    const { name, value } = e.target;
    setFormData((prev) => ({ ...prev, [name]: value }));
  };

  const handleSave = async () => {
    try {

      const dataToSend = { ...formData };

      if (!dataToSend.password) {
        delete dataToSend.password;
      }

      const res = await axios.patch(
        `/api/admin/user/${editingUser.id}`,
        dataToSend,
        {
          headers: {
            Authorization: `Bearer ${localStorage.getItem("token")}`,
          },
        }
      );

      setUsers((prev) =>
        prev.map((u) => (u.id === editingUser.id ? res.data.user : u))
      );

      setEditingUser(null);
      alert("User updated successfully!");
    } catch (error) {
      console.error("Error updating user:", error.response?.data || error.message);
      alert("Error updating user.");
    }
  };

  if (loading) return <p className="text-muted">Loading users...</p>;

  return (
    <div className="p-6 min-h-screen">
      <div className="overflow-x-auto bg-white rounded-xl shadow-sm border border-foreground/10 p-4">
        <table className="w-full table-auto border-collapse">
          <thead className="bg-foreground/5">
            <tr>
              <th className="p-2">ID</th>
              <th className="p-2">First Name</th>
              <th className="p-2">Last Name</th>
              <th className="p-2">Email</th>
              <th className="p-2">Role</th>
              <th className="p-2">Actions</th>
            </tr>
          </thead>
          <tbody>
            {users.map((user) => (
              <tr key={user.id} className="border-b border-foreground/10 hover:bg-foreground/5">
                <td className="p-2">{user.id}</td>
                <td className="p-2">{user.first_name}</td>
                <td className="p-2">{user.last_name}</td>
                <td className="p-2">{user.email}</td>
                <td className="p-2">{user.role}</td>
                <td className="p-2 space-x-2">
                  <button
                    className="bg-foreground/5 hover:bg-foreground/10 text-foreground px-3 py-1 rounded-lg transition-colors cursor-pointer"
                    onClick={() => navigate(`/views/adminPanel/user/${user.id}`)}
                  >
                    Details
                  </button>
                  <button
                    className="bg-foreground/5 hover:bg-foreground/10 text-foreground px-3 py-1 rounded-lg transition-colors cursor-pointer"
                    onClick={() => openEditModal(user)}
                  >
                    Edit
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {editingUser && (
        <div className="fixed inset-0 flex items-center justify-center bg-foreground/50">
          <div className="bg-white p-6 rounded-lg shadow-xl border border-foreground/10 w-96">
            <h2 className="text-xl font-bold mb-4">Edit User</h2>

            <label className="block mb-2 text-sm">
              First Name:
              <Input
                type="text"
                name="first_name"
                value={formData.first_name}
                onChange={handleChange}
                className="mt-1"
              />
            </label>

            <label className="block mb-2 text-sm">
              Last Name:
              <Input
                type="text"
                name="last_name"
                value={formData.last_name}
                onChange={handleChange}
                className="mt-1"
              />
            </label>

            <label className="block mb-2 text-sm">
              Email:
              <Input
                type="email"
                name="email"
                value={formData.email}
                onChange={handleChange}
                className="mt-1"
              />
            </label>

            <label className="block mb-4 text-sm">
              Role:
              <select
                name="role"
                value={formData.role}
                onChange={handleChange}
                className="w-full border border-foreground/15 rounded-md p-2 mt-1 bg-transparent focus:outline-none focus:ring-2 focus:ring-accent"
              >
                <option value="user">User</option>
                <option value="admin">Admin</option>
              </select>
            </label>

            <label className="block mb-2 text-sm">
              New password:
              <Input
                type="password"
                name="password"
                value={formData.password}
                onChange={handleChange}
                className="mt-1"
              />
            </label>

            <div className="flex justify-end space-x-2 mt-2">
              <Button variant="outline" onClick={() => setEditingUser(null)}>
                Cancel
              </Button>
              <Button onClick={handleSave}>
                Save
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
